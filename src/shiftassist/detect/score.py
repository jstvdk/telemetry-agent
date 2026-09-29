"""Score detector events against validated labels.

Matching (per expected event of a label): same kind and subsystem, event start inside the
label's evidence window (as used by label validation), same channel if the label names one.
Localisation: if the label names an entity (a module), an event on that entity is an *exact*
match; an event without entity (e.g. a log burst: the log line does not say which module, R18)
is a *partial* match; an event on another entity does not match.

One event, one expected event: credit is assigned by a minimum-cost bipartite matching between
expected events and events, so an event can explain at most one expected event (two
overlapping faults need two events). The cost is lexicographic: first as many expected events
matched as possible, then as many exact localisations, then the smallest total delay from
fault start to event, so an event is credited to the fault it most plausibly belongs to.

Events are then classified:
    true positive   assigned to an expected event
    duplicate       matches an expected event that another event was assigned to
    explained       inside a fault window (start-60 s … end+180 s) but not an expected event,
                    e.g. a side effect (a new message template, a counter reset)
    false alarm     none of these
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
    duplicates: list[Event]
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
        return len(self.tp) + len(self.duplicates) + len(self.explained) + len(self.false_alarms)

    @property
    def precision_strict(self) -> float:
        return len(self.tp) / max(self.n_events, 1)

    @property
    def precision_lenient(self) -> float:
        return (len(self.tp) + len(self.duplicates) + len(self.explained)) / max(self.n_events, 1)

    @property
    def false_alarms_per_hour(self) -> float:
        return len(self.false_alarms) / max(self.hours, 1e-9)


UNMATCHED, PARTIAL = 1e9, 1e6  # cost scale: one miss > any partial > any delay (seconds)


def _assign(cost: list[list[float | None]]) -> dict[int, int]:
    """Minimum-cost assignment of rows (expected events) to columns (events), Hungarian method.
    cost[i][j] is None where event j cannot explain expected event i. Returns row -> column for
    matched rows only."""
    n, m = len(cost), len(cost[0]) if cost else 0
    cols = m + n  # one private "unmatched" column per row
    inf = float("inf")

    def c(i: int, j: int) -> float:
        if j < m:
            v = cost[i][j]
            return inf if v is None else v
        return UNMATCHED if j - m == i else inf

    u, v = [0.0] * (n + 1), [0.0] * (cols + 1)
    p, way = [0] * (cols + 1), [0] * (cols + 1)  # 1-based, column 0 is the virtual start
    for i in range(1, n + 1):
        p[0], j0 = i, 0
        minv, used = [inf] * (cols + 1), [False] * (cols + 1)
        while True:
            used[j0], i0, delta, j1 = True, p[j0], inf, 0
            for j in range(1, cols + 1):
                if not used[j]:
                    cur = c(i0 - 1, j - 1) - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(cols + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
    return {p[j] - 1: j - 1 for j in range(1, m + 1) if p[j]}


def score(capture: str, events: list[Event], labels: list[Label], hours: float) -> Score:
    pairs = [(lb, exp) for lb in labels for exp in lb.expected_events]
    how = [[match(e, lb, exp) for e in events] for lb, exp in pairs]
    cost: list[list[float | None]] = [
        [
            None
            if m is None
            else (m != "exact") * PARTIAL + abs((e.ts - parse_iso(lb.start)).total_seconds())
            for e, m in zip(events, row, strict=True)
        ]
        for (lb, _), row in zip(pairs, how, strict=True)
    ]
    assigned = _assign(cost)
    results: list[ExpectedResult] = []
    for i, (lb, exp) in enumerate(pairs):
        r = ExpectedResult(lb, exp, None)
        if i in assigned:
            j = assigned[i]
            r.how, r.events = how[i][j], [events[j].event_id]
            r.delay_s = (events[j].ts - parse_iso(lb.start)).total_seconds()
        results.append(r)
    used = set(assigned.values())
    candidate = {j for row in how for j, m in enumerate(row) if m}
    windows = [
        (parse_iso(lb.start) - EXPLAIN_BEFORE, parse_iso(lb.end) + EXPLAIN_AFTER) for lb in labels
    ]
    tp, dup, explained, fa = [], [], [], []
    for j, e in enumerate(events):
        if j in used:
            tp.append(e)
        elif j in candidate:
            dup.append(e)
        elif any(a <= e.ts <= b for a, b in windows):
            explained.append(e)
        else:
            fa.append(e)
    return Score(capture, hours, results, tp, dup, explained, fa)


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
        f"| precision, lenient (+ duplicates, side effects in a fault window) "
        f"| {s.precision_lenient:.0%} |",
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
    for title, evs in (
        ("False alarms", s.false_alarms),
        ("Duplicates (a real fault, already credited to another event)", s.duplicates),
        ("Explained side effects", s.explained),
    ):
        out += ["", f"## {title} ({len(evs)})", ""]
        out += [
            f"- `{e.event_id}` {e.ts:%H:%M:%S} {e.kind} {e.subsystem}"
            f"{'/' + e.entity if e.entity else ''}: {e.summary}"
            for e in evs[:40]
        ]
        if len(evs) > 40:
            out.append(f"- … {len(evs) - 40} more")
    return "\n".join(out) + "\n"
