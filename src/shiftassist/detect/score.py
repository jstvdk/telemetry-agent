"""Score detector events against validated labels.

Matching (per expected event of a label): same kind and subsystem, event start inside the
label's evidence window (as used by label validation), same channel if the label names one.
Localisation: if the label names an entity (a module), an event on that entity is an *exact*
match; an event without entity (e.g. a log burst: the log line does not say which module, R18)
is a *partial* match; an event on another entity does not match.

Events are then classified:
    true positive   matches at least one expected event
    explained       inside a fault window (start-60 s … end+180 s) but not an expected event,
                    e.g. a side effect (a new message template, a counter reset)
    false alarm     neither
"""

from dataclasses import dataclass, field
from datetime import timedelta

from shiftassist.collect.evidence import _window
from shiftassist.detect.model import Event
from shiftassist.sim.records import ExpectedEvent, Label
from shiftassist.sim.timeutil import parse_iso

EXPLAIN_BEFORE = timedelta(seconds=60)
EXPLAIN_AFTER = timedelta(seconds=180)


def match(ev: Event, label: Label, exp: ExpectedEvent) -> str | None:
    if ev.kind != exp.kind or ev.subsystem != exp.subsystem:
        return None
    a, b = _window(label, exp)
    if not a <= ev.ts <= b:
        return None
    if exp.channel and ev.channel != exp.channel:
        return None
    if exp.entity:
        if ev.entity == exp.entity:
            return "exact"
        return "partial" if ev.entity is None else None
    return "exact"


@dataclass
class ExpectedResult:
    label: Label
    expected: ExpectedEvent
    how: str | None  # 'exact' | 'partial' | None
    events: list[str] = field(default_factory=list)
    delay_s: float | None = None


@dataclass
class Score:
    capture: str
    hours: float
    expected: list[ExpectedResult]
    tp: list[Event]
    explained: list[Event]
    false_alarms: list[Event]

    @property
    def recall(self) -> float:
        return sum(r.how is not None for r in self.expected) / max(len(self.expected), 1)

    @property
    def recall_exact(self) -> float:
        return sum(r.how == "exact" for r in self.expected) / max(len(self.expected), 1)

    @property
    def n_events(self) -> int:
        return len(self.tp) + len(self.explained) + len(self.false_alarms)

    @property
    def precision_strict(self) -> float:
        return len(self.tp) / max(self.n_events, 1)

    @property
    def precision_lenient(self) -> float:
        return (len(self.tp) + len(self.explained)) / max(self.n_events, 1)

    @property
    def false_alarms_per_hour(self) -> float:
        return len(self.false_alarms) / max(self.hours, 1e-9)


def score(capture: str, events: list[Event], labels: list[Label], hours: float) -> Score:
    results: list[ExpectedResult] = []
    matched_ids: set[str] = set()
    for lb in labels:
        start = parse_iso(lb.start)
        for exp in lb.expected_events:
            hits = [(e, m) for e in events if (m := match(e, lb, exp))]
            how = "exact" if any(m == "exact" for _, m in hits) else ("partial" if hits else None)
            r = ExpectedResult(lb, exp, how, [e.event_id for e, _ in hits])
            if hits:
                first = min(e.ts for e, _ in hits)
                r.delay_s = (first - start).total_seconds()
                matched_ids |= {e.event_id for e, _ in hits}
            results.append(r)
    windows = [
        (parse_iso(lb.start) - EXPLAIN_BEFORE, parse_iso(lb.end) + EXPLAIN_AFTER) for lb in labels
    ]
    tp, explained, fa = [], [], []
    for e in events:
        if e.event_id in matched_ids:
            tp.append(e)
        elif any(a <= e.ts <= b for a, b in windows):
            explained.append(e)
        else:
            fa.append(e)
    return Score(capture, hours, results, tp, explained, fa)


def render(s: Score) -> str:
    out = [
        f"# Detection score: {s.capture}",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| expected events | {len(s.expected)} |",
        f"| recall (any localisation) | {s.recall:.0%} |",
        f"| recall (exact entity) | {s.recall_exact:.0%} |",
        f"| detector events | {s.n_events} |",
        f"| precision, strict (matches an expected event) | {s.precision_strict:.0%} |",
        f"| precision, lenient (+ side effects in a fault window) | {s.precision_lenient:.0%} |",
        f"| false alarms (outside every fault window) | {len(s.false_alarms)} |",
        f"| false alarms per hour | {s.false_alarms_per_hour:.2f} |",
        "",
    ]
    by_kind: dict[str, list[ExpectedResult]] = {}
    for r in s.expected:
        by_kind.setdefault(r.expected.kind, []).append(r)
    if by_kind:
        out += [
            "## Recall by event kind",
            "",
            "| kind | found | of | median delay (s) |",
            "|---|---:|---:|---:|",
        ]
        for k, rs in sorted(by_kind.items()):
            ds = sorted(r.delay_s for r in rs if r.delay_s is not None)
            med = f"{ds[len(ds) // 2]:.0f}" if ds else "-"
            out.append(f"| {k} | {sum(r.how is not None for r in rs)} | {len(rs)} | {med} |")
        out += [
            "",
            "## Per expected event",
            "",
            "| label | fault | expected | source | result | delay (s) | events |",
            "|---|---|---|---|---|---:|---|",
        ]
        for r in s.expected:
            src = r.expected.subsystem + (f"/{r.expected.entity}" if r.expected.entity else "")
            src += f" {r.expected.channel}" if r.expected.channel else ""
            res = {"exact": "✅", "partial": "🟡 no entity", None: "❌ missed"}[r.how]
            d = f"{r.delay_s:.0f}" if r.delay_s is not None else "-"
            out.append(
                f"| {r.label.label_id} | {r.label.kind} | {r.expected.kind} | {src} | {res} "
                f"| {d} | {', '.join(r.events[:4])} |"
            )
    for title, evs in (("False alarms", s.false_alarms), ("Explained side effects", s.explained)):
        out += ["", f"## {title} ({len(evs)})", ""]
        out += [
            f"- `{e.event_id}` {e.ts:%H:%M:%S} {e.kind} {e.subsystem}"
            f"{'/' + e.entity if e.entity else ''}: {e.summary}"
            for e in evs[:40]
        ]
        if len(evs) > 40:
            out.append(f"- … {len(evs) - 40} more")
    return "\n".join(out) + "\n"
