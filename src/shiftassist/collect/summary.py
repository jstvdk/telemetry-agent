"""Summarise one camera capture (camera-in-a-box ``capture.sh`` layout) as a markdown report.

    capture/
      data/logs/log_<start>_<process>.txt   per-process logs (pipe format)
      data/logs/sstcam-server_<date>.log    central log (ICD format)
      journal.jsonl                          journalctl -o json
      monitoring.jsonl                       decoded gatherer monitoring

The report is what "normal" looks like for this camera: volumes, message templates and their
rates, everything at WARNING or above, process lifecycle, central-log completeness, and
monitoring rates and value ranges. It is the reference that detection rules are tuned against.
"""

import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from shiftassist.collect.journal import parse_journal
from shiftassist.collect.model import LEVELS, Entry, Sample
from shiftassist.collect.monitoring import iter_samples
from shiftassist.collect.sstcam_logs import read_log_file

_MASKS = [
    (re.compile(r"'[^']*'|\"[^\"]*\""), "<str>"),
    (re.compile(r"(?:/[\w.@+-]+)+/?"), "<path>"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"), "<ip>"),
    (re.compile(r"\b0x[0-9a-fA-F]+\b"), "<hex>"),
    (re.compile(r"[-+]?\b\d+(?:\.\d+)?(?:e[-+]?\d+)?\b"), "<n>"),
]


def template(message: str) -> str:
    """First line of a message with variable parts masked (a cheap stand-in for drain3)."""
    t = message.split("\n", 1)[0]
    for rx, repl in _MASKS:
        t = rx.sub(repl, t)
    return re.sub(r"\s+", " ", t).strip()[:140]


@dataclass
class _Stat:
    n: int = 0
    mean: float = 0.0
    m2: float = 0.0
    lo: float = math.inf
    hi: float = -math.inf

    def add(self, x: float) -> None:  # Welford
        self.n += 1
        d = x - self.mean
        self.mean += d / self.n
        self.m2 += d * (x - self.mean)
        self.lo, self.hi = min(self.lo, x), max(self.hi, x)

    @property
    def std(self) -> float:
        return math.sqrt(self.m2 / (self.n - 1)) if self.n > 1 else 0.0


@dataclass
class CaptureSummary:
    name: str
    first: datetime | None = None
    last: datetime | None = None
    files: list[tuple[str, int, int]] = field(default_factory=list)  # name, lines, entries
    by_process_level: Counter[tuple[str, str]] = field(default_factory=Counter)
    templates: Counter[tuple[str, str, str]] = field(default_factory=Counter)  # proc, level, tpl
    multiline: int = 0
    central_missing: dict[str, tuple[int, int, str, str]] = field(default_factory=dict)
    unit_events: Counter[tuple[str, str]] = field(default_factory=Counter)
    unit_exits: list[Entry] = field(default_factory=list)
    tracebacks: list[Entry] = field(default_factory=list)
    stdout: Counter[str] = field(default_factory=Counter)
    mon_msgs: Counter[str] = field(default_factory=Counter)
    mon_span: dict[str, tuple[datetime, datetime]] = field(default_factory=dict)
    mon_stats: dict[tuple[str, str], _Stat] = field(default_factory=lambda: defaultdict(_Stat))
    mon_entities: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))

    @property
    def minutes(self) -> float:
        if not (self.first and self.last):
            return 0.0
        return max((self.last - self.first).total_seconds() / 60, 1e-9)

    def _seen(self, ts: datetime) -> None:
        self.first = ts if self.first is None or ts < self.first else self.first
        self.last = ts if self.last is None or ts > self.last else self.last


def summarise(capture: str | Path) -> CaptureSummary:
    cap = Path(capture)
    s = CaptureSummary(name=cap.name)
    logs = cap / "data" / "logs"

    central_keys: Counter[tuple[datetime, str, str]] = Counter()
    for f in sorted(logs.glob("sstcam-server_*.log")):
        entries = list(read_log_file(f))
        s.files.append((f.name, _count_lines(f), len(entries)))
        for e in entries:
            central_keys[(e.ts.replace(microsecond=0), e.process, e.message)] += 1

    for f in sorted(logs.glob("log_*.txt")):
        entries = list(read_log_file(f))
        s.files.append((f.name, _count_lines(f), len(entries)))
        own = "gatherer_serve" not in f.name  # the gatherer's file mirrors the central log
        missing: list[Entry] = []
        for e in entries:
            s._seen(e.ts)
            if not own:
                continue
            s.by_process_level[(e.process, e.level)] += 1
            s.templates[(e.process, e.level, template(e.message))] += 1
            s.multiline += "\n" in e.message
            k = (e.ts, e.process, e.message)
            if central_keys[k] > 0:
                central_keys[k] -= 1
            else:
                missing.append(e)
        if own and missing:
            s.central_missing[f.name] = (
                len(entries),
                len(missing),
                f"{missing[0].ts:%H:%M:%S}",
                f"{missing[-1].ts:%H:%M:%S}",
            )

    journal = cap / "journal.jsonl"
    if journal.exists():
        with journal.open() as fh:
            for e in parse_journal(fh):
                if e.kind == "unit":
                    ev = e.fields.get("event", "other")
                    s.unit_events[(e.unit or "", ev)] += 1
                    if ev in ("exited", "control_failed"):
                        s.unit_exits.append(e)
                elif e.kind == "traceback":
                    s.tracebacks.append(e)
                elif e.kind == "stdout":
                    s.stdout[e.message[:100]] += 1

    mon = cap / "monitoring.jsonl"
    if mon.exists():
        with mon.open() as fh:
            _add_samples(s, iter_samples(fh))
    return s


def _add_samples(s: CaptureSummary, samples: Iterable[Sample]) -> None:
    last_msg: dict[tuple[str, str], datetime] = {}
    for x in samples:
        key = (x.subsystem, x.entity)
        if last_msg.get(key) != x.ts:  # one message = several samples with the same ts
            last_msg[key] = x.ts
            s.mon_msgs[x.subsystem] += 1
            lo, hi = s.mon_span.get(x.subsystem, (x.ts, x.ts))
            s.mon_span[x.subsystem] = (min(lo, x.ts), max(hi, x.ts))
        if x.entity:
            s.mon_entities[x.subsystem].add(x.entity)
        s.mon_stats[(x.subsystem, x.channel)].add(x.value)


def _count_lines(p: Path) -> int:
    with p.open("rb") as fh:
        return sum(1 for _ in fh)


# --- markdown ---------------------------------------------------------------------------------


def render(s: CaptureSummary, top: int = 25) -> str:
    out: list[str] = [f"# Capture summary: {s.name}", ""]
    if s.first and s.last:
        out += [
            f"Log window **{s.first:%Y-%m-%d %H:%M:%S} → {s.last:%H:%M:%S} UTC** "
            f"({s.minutes:.1f} min).",
            "",
        ]

    lines = sum(n for _, n, _ in s.files)
    entries = sum(n for _, _, n in s.files)
    out += [
        "## Log volume",
        "",
        f"{len(s.files)} files, {lines:,} lines → {entries:,} entries "
        f"({s.multiline:,} multi-line entries in per-process files).",
        "",
        "| process | " + " | ".join(lv for lv in LEVELS if lv != "VERBOSE") + " | per min |",
        "|---|" + "---:|" * (len(LEVELS)),
    ]
    procs = sorted({p for p, _ in s.by_process_level})
    for p in procs:
        row = [s.by_process_level[(p, lv)] for lv in LEVELS if lv != "VERBOSE"]
        out.append(
            f"| {p} | "
            + " | ".join(str(v) if v else "·" for v in row)
            + f" | {sum(row) / s.minutes:.1f} |"
        )

    warn = [(k, n) for k, n in s.templates.items() if LEVELS.get(k[1], 0) >= LEVELS["WARNING"]]
    out += ["", "## WARNING and above (all templates)", ""]
    if warn:
        out += ["| process | level | template | count | per min |", "|---|---|---|---:|---:|"]
        for (p, lv, t), n in sorted(warn, key=lambda kv: -kv[1]):
            out.append(f"| {p} | {lv} | `{t}` | {n} | {n / s.minutes:.2f} |")
    else:
        out.append("None.")

    out += [
        "",
        f"## Top {top} message templates",
        "",
        "| process | level | template | count | per min |",
        "|---|---|---|---:|---:|",
    ]
    for (p, lv, t), n in s.templates.most_common(top):
        out.append(f"| {p} | {lv} | `{t}` | {n} | {n / s.minutes:.2f} |")

    out += ["", "## Process lifecycle (journal)", ""]
    units = sorted({u for u, _ in s.unit_events})
    evs = ["started", "stopping", "stopped", "exited", "failed", "restart_scheduled"]
    out += ["| unit | " + " | ".join(evs) + " |", "|---|" + "---:|" * len(evs)]
    for u in units:
        out.append(f"| {u} | " + " | ".join(str(s.unit_events[(u, e)] or "·") for e in evs) + " |")
    if s.unit_exits:
        out += ["", "Exits:", ""]
        out += [
            f"- {e.ts:%H:%M:%S} `{e.unit}` {e.fields.get('event')} "
            f"code={e.fields.get('code')} status={e.fields.get('status')}"
            for e in s.unit_exits
        ]
    out += ["", f"Tracebacks (journal only): **{len(s.tracebacks)}**", ""]
    out += [
        f"- {e.ts:%H:%M:%S} `{e.unit}` {e.fields['exception_line'][:160]}" for e in s.tracebacks
    ]
    if s.stdout:
        out += ["", "Other raw output:", ""]
        out += [f"- `{m}` x {n}" for m, n in s.stdout.most_common(10)]

    out += ["", "## Central log completeness", ""]
    if s.central_missing:
        out += [
            "Per-process records not found in the central log:",
            "",
            "| file | records | missing | window |",
            "|---|---:|---:|---|",
        ]
        for f, (n, m, a, b) in sorted(s.central_missing.items()):
            out.append(f"| {f} | {n} | {m} | {a}-{b} |")
    else:
        out.append("Every per-process record is also in the central log.")

    out += [
        "",
        "## Monitoring",
        "",
        "| subsystem | messages | per s | entities | channels |",
        "|---|---:|---:|---:|---:|",
    ]
    for sub, n in sorted(s.mon_msgs.items()):
        t0, t1 = s.mon_span[sub]
        secs = max((t1 - t0).total_seconds(), 1e-9)
        per_entity = n / max(len(s.mon_entities.get(sub, ())) or 1, 1)
        nch = sum(1 for k in s.mon_stats if k[0] == sub)
        ents = len(s.mon_entities.get(sub, ())) or "·"
        out.append(f"| {sub} | {n:,} | {per_entity / secs:.2f} | {ents} | {nch} |")
    out += [
        "",
        "Value ranges (chiller, slowboard; slow-signal temperatures/HV across all modules):",
        "",
        "| channel | n | min | mean | max | std |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for (sub, ch), st in sorted(s.mon_stats.items()):
        interesting = sub in ("chiller", "slowboard") or (
            sub == "slowsignal" and ch.startswith(("temperature_", "hv_"))
        )
        if interesting and st.n:
            out.append(
                f"| {sub}.{ch} | {st.n} | {st.lo:.3g} | {st.mean:.4g} | {st.hi:.3g} "
                f"| {st.std:.3g} |"
            )
    return "\n".join(out) + "\n"
