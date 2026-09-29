"""Agent evaluation on a labelled capture (docs/04-evaluation.md, layers 2-6).

Questions come from the labels: one per fault, or per group of overlapping faults, asked about a
window around it ("what happened, what should the operator do?"). The model never sees labels.

Scored per run, deterministically:
  layer 2  submitted, schema errors, tool errors, steps
  layer 3  runbook_ok: the answer names the expected entry (or, for a fault type the runbook does
           not cover, status not_in_runbook and no entry); evidence recall: share of the events the
           detector scorer credited to these faults that the answer cites
  layer 4  hallucinated citations, flags (from the validator); evidence precision: share of cited
           events that belong to these faults
  layer 5  input/output tokens
  layer 6  pass^k: every one of k runs has runbook_ok
Rubric scoring of the explanation needs a calibrated judge (D-05d) and is not done here.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from shiftassist.agent.loop import RunResult, run
from shiftassist.agent.providers import Provider
from shiftassist.detect.model import Event
from shiftassist.detect.score import score
from shiftassist.sim.records import Label
from shiftassist.sim.timeutil import parse_iso
from shiftassist.tools import Snapshot

BEFORE, AFTER = timedelta(seconds=60), timedelta(seconds=180)
QUESTION = (
    "What happened on the camera between {a} and {b} UTC? Explain the cause, and tell the "
    "operator what to check or do."
)


@dataclass
class Question:
    qid: str
    text: str
    window: tuple[datetime, datetime]
    labels: list[Label]
    expected_entries: set[str]  # empty: no entry applies (not_in_runbook expected)
    credited_events: set[str]


def expected_entry(label: Label, runbook_map: dict[str, Any]) -> set[str]:
    """runbook_map: {kind: entry | "none" | {unit: entry, default: entry}}; entry = "RB-x" or
    a list of acceptable IDs."""
    m = runbook_map.get(label.kind)
    if m is None:
        raise KeyError(f"runbook map has no entry for fault kind {label.kind!r}")
    if isinstance(m, dict):
        unit = label.details.get("fault", {}).get("unit")
        m = m.get(unit, m.get("default"))
    if m in (None, "none"):
        return set()
    return {m} if isinstance(m, str) else set(m)


def questions(snap: Snapshot, labels: list[Label], runbook_map: dict[str, Any]) -> list[Question]:
    s = score(snap.camera, snap.events, labels, 1.0)
    credited: dict[str, set[str]] = {}
    for r in s.expected:
        credited.setdefault(r.label.label_id, set()).update(r.events)
    groups: list[list[Label]] = []
    for lb in sorted(labels, key=lambda x: x.start):
        if groups and parse_iso(lb.start) <= max(parse_iso(x.end) for x in groups[-1]):
            groups[-1].append(lb)  # starts while the previous fault is still active
        else:
            groups.append([lb])
    out = []
    for n, g in enumerate(groups):
        a = min(parse_iso(x.start) for x in g) - BEFORE
        b = max(parse_iso(x.end) for x in g) + AFTER
        if n + 1 < len(groups):  # one incident per question: stop before the next fault starts
            b = min(b, min(parse_iso(x.start) for x in groups[n + 1]) - timedelta(seconds=5))
        if n > 0:
            a = max(a, max(parse_iso(x.end) for x in groups[n - 1]) + timedelta(seconds=5))
        exp = [expected_entry(x, runbook_map) for x in g]
        out.append(
            Question(
                qid="+".join(x.label_id for x in g),
                text=QUESTION.format(a=f"{a:%H:%M:%S}", b=f"{b:%H:%M:%S}"),
                window=(a, b),
                labels=g,
                # a group is answered well if the entry of any of its faults is named
                expected_entries=set().union(*exp) if all(exp) else set(),
                credited_events=set().union(*(credited.get(x.label_id, set()) for x in g)),
            )
        )
    return out


def score_run(q: Question, res: RunResult, events: list[Event]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "qid": q.qid,
        "submitted": res.stop == "submitted",
        "stop": res.stop,
        "schema_errors": res.schema_errors,
        "tool_errors": res.tool_errors,
        "steps": len(res.steps),
        **{k: res.usage.get(k, 0) for k in ("input_tokens", "output_tokens")},
    }
    if res.answer is None or res.validation is None:
        return row | {"runbook_ok": False, "evidence_recall": 0.0, "evidence_precision": None}
    a, v = res.answer, res.validation
    if q.expected_entries:
        ok = a.status == "answered" and a.runbook_entry in q.expected_entries
    else:
        ok = a.status == "not_in_runbook" and not a.runbook_entry
    cited = {c for chk in v.kept for c in chk.claim.citations if c.startswith("EV-")}
    in_window = {e.event_id for e in events if q.window[0] <= e.ts <= q.window[1]}
    return row | {
        "status": a.status,
        "runbook_entry": a.runbook_entry,
        "runbook_ok": ok,
        "evidence_recall": (
            len(cited & q.credited_events) / len(q.credited_events) if q.credited_events else None
        ),
        "cited_events": len(cited),
        "evidence_precision": len(cited & q.credited_events) / len(cited) if cited else None,
        "evidence_precision_lenient": len(cited & (q.credited_events | in_window)) / len(cited)
        if cited
        else None,
        "hallucinated_citations": v.hallucinated_citations,
        "flags": dict(v.flag_counts),
    }


@dataclass
class Report:
    capture: str
    config: dict[str, Any]
    rows: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        n = len(self.rows)
        by_q: dict[str, list[dict[str, Any]]] = {}
        for r in self.rows:
            by_q.setdefault(r["qid"], []).append(r)

        def mean(key: str) -> float | None:
            xs = [r[key] for r in self.rows if r.get(key) is not None]
            return sum(xs) / len(xs) if xs else None

        return {
            "runs": n,
            "questions": len(by_q),
            "submitted": mean("submitted"),
            "runbook_ok": mean("runbook_ok"),
            "pass_k": sum(all(r["runbook_ok"] for r in rs) for rs in by_q.values())
            / max(len(by_q), 1),
            "evidence_recall": mean("evidence_recall"),
            "evidence_precision": mean("evidence_precision"),
            "evidence_precision_lenient": mean("evidence_precision_lenient"),
            "cited_events_mean": mean("cited_events"),
            "hallucinated_citations": sum(r.get("hallucinated_citations", 0) for r in self.rows),
            "schema_errors": sum(r["schema_errors"] for r in self.rows),
            "tool_errors": sum(r["tool_errors"] for r in self.rows),
            "steps_mean": mean("steps"),
            "input_tokens": sum(r["input_tokens"] for r in self.rows),
            "output_tokens": sum(r["output_tokens"] for r in self.rows),
        }


def evaluate(
    snap: Snapshot,
    labels: list[Label],
    runbook_map: dict[str, Any],
    make_provider: Callable[[], Provider],
    use_runbook: bool = True,
    k: int = 1,
    runs_dir: Path | None = None,
) -> Report:
    qs = questions(snap, labels, runbook_map)
    p = make_provider()
    rep = Report(
        snap.camera, {"provider": p.name, "model": p.model, "use_runbook": use_runbook, "k": k}
    )
    for q in qs:
        for i in range(k):
            res = run(q.text, snap, make_provider(), q.window, use_runbook)
            row = score_run(q, res, snap.events) | {"repeat": i}
            rep.rows.append(row)
            if runs_dir:
                runs_dir.mkdir(parents=True, exist_ok=True)
                name = f"{q.qid}-{'rb' if use_runbook else 'norb'}-{i}.json"
                (runs_dir / name).write_text(
                    json.dumps(res.to_json() | {"score": row}, indent=2, default=str)
                )
    return rep


def load_map(path: str | Path) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text())
    return dict(data)
