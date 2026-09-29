"""Grounding validator (ADR-0005): plain code, no model. Checks every claim of an answer.

V1  the claim cites something                       else flag   uncited
V2  every citation resolves in the snapshot         else DROP   (hallucinated citation)
V3  cited events lie in the question's window       else flag   out_of_window
V4  every stated value appears in what it cites     else flag   value_mismatch
V5  cited runbook entries are verified              else flag   unverified_source (shown)

It checks that the evidence exists and says what the claim says it says, not that the reasoning
is right; reasoning is scored separately.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from shiftassist.agent.answer import Answer, Claim
from shiftassist.tools.core import get_telemetry_features
from shiftassist.tools.snapshot import Snapshot

EV = re.compile(r"^EV-\d{6}$")
RB = re.compile(r"^RB-\d{3}$")
TEL = re.compile(r"^telemetry:([^/]+)/([^/]+)/([^@]+)@([^/]+Z)/([^/]+Z)$")
NUM = re.compile(r"-?\d+(?:\.\d+)?")
REL_TOL, ABS_TOL = 0.05, 0.05
WINDOW_SLACK = timedelta(minutes=2)


@dataclass
class ClaimCheck:
    claim: Claim
    dropped: bool = False
    flags: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    unmatched_values: list[str] = field(default_factory=list)


@dataclass
class Validation:
    checks: list[ClaimCheck]
    answer_flags: list[str]

    @property
    def kept(self) -> list[ClaimCheck]:
        return [c for c in self.checks if not c.dropped]

    @property
    def hallucinated_citations(self) -> int:
        return sum(len(c.unresolved) for c in self.checks)

    @property
    def flag_counts(self) -> Counter[str]:
        return Counter(f for c in self.checks for f in c.flags) + Counter(self.answer_flags)

    def summary(self) -> dict[str, Any]:
        return {
            "claims": len(self.checks),
            "kept": len(self.kept),
            "dropped": len(self.checks) - len(self.kept),
            "hallucinated_citations": self.hallucinated_citations,
            "flags": dict(self.flag_counts),
        }


def _numbers(x: Any) -> list[float]:
    if isinstance(x, bool):
        return []
    if isinstance(x, int | float):
        return [float(x)]
    if isinstance(x, str):
        return [float(n) for n in NUM.findall(x)]
    if isinstance(x, dict):
        return [n for v in x.values() for n in _numbers(v)]
    if isinstance(x, list):
        return [n for v in x for n in _numbers(v)]
    return []


def _close(v: float, pool: list[float]) -> bool:
    return any(abs(v - n) <= max(REL_TOL * abs(n), ABS_TOL) for n in pool)


def _resolve(cit: str, snap: Snapshot) -> tuple[bool, list[float], datetime | None, str | None]:
    """(resolves, numbers it contains, event time, runbook status)."""
    if EV.match(cit):
        e = snap.by_id.get(cit)
        if e is None:
            return False, [], None, None
        return True, _numbers(e.evidence) + _numbers(e.summary), e.ts, None
    if RB.match(cit):
        r = snap.runbook.entries.get(cit)
        return (r is not None), [], None, (r.status if r else None)
    if m := TEL.match(cit):
        sub, ent, ch, a, b = m.groups()
        try:
            f = get_telemetry_features(snap, sub, ch, None if ent == "-" else ent, a, b)
        except (LookupError, ValueError):
            return False, [], None, None
        return True, _numbers({k: v for k, v in f.items() if k != "window"}), None, None
    x = snap.entry(cit)
    if x is None:
        return False, [], None, None
    return True, _numbers(x.message), x.ts, None


def validate(
    ans: Answer, snap: Snapshot, window: tuple[datetime, datetime] | None = None
) -> Validation:
    checks = []
    for claim in ans.claims:
        c = ClaimCheck(claim)
        if not claim.citations:
            c.flags.append("uncited")  # V1
        pool: list[float] = []
        for cit in claim.citations:
            ok, nums, ts, rb_status = _resolve(cit.strip(), snap)
            if not ok:
                c.unresolved.append(cit)  # V2
                continue
            pool += nums
            if window and ts and not (window[0] - WINDOW_SLACK <= ts <= window[1] + WINDOW_SLACK):
                c.flags.append("out_of_window")  # V3
            if rb_status is not None and rb_status != "verified":
                c.flags.append("unverified_source")  # V5
        c.dropped = bool(c.unresolved)
        for name, v in claim.values.items():
            if not _close(v, pool):
                c.unmatched_values.append(name)  # V4
        if c.unmatched_values:
            c.flags.append("value_mismatch")
        c.flags = sorted(set(c.flags))
        checks.append(c)

    answer_flags = []
    if ans.runbook_entry:
        r = snap.runbook.entries.get(ans.runbook_entry)
        if r is None:
            answer_flags.append("runbook_entry_unresolved")
        elif r.status != "verified":
            answer_flags.append("runbook_entry_draft")
    return Validation(checks, answer_flags)


def render(ans: Answer, v: Validation) -> str:
    """What the operator sees: the answer, then each claim with its marks."""
    mark = {"uncited": "⚠ uncited", "out_of_window": "⚠ outside the window",
            "value_mismatch": "⚠ value not in cited evidence",
            "unverified_source": "📝 draft runbook"}  # fmt: skip
    out = [f"**{ans.status}**: {ans.answer}", ""]
    if ans.runbook_entry:
        draft = " (draft)" if "runbook_entry_draft" in v.answer_flags else ""
        out.append(f"Runbook: {ans.runbook_entry}{draft}")
    for c in v.checks:
        if c.dropped:
            out.append(
                f"- ~~{c.claim.text}~~ ❌ removed: cites {', '.join(c.unresolved)}, "
                "which do not exist"
            )
            continue
        marks = " ".join(mark[f] for f in c.flags)
        out.append(f"- {c.claim.text} [{', '.join(c.claim.citations)}] {marks}".rstrip())
    if ans.recommended_checks:
        out += ["", "Next checks:", *[f"- {r}" for r in ans.recommended_checks]]
    return "\n".join(out)
