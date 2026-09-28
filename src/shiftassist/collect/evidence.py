"""Check that each label's expected events are actually visible in a capture.

This validates the *ground truth*, not a detector: it is told where to look (label window,
subsystem, entity, channel) and only answers "is the signal there?". A label whose evidence is
missing means the fault did not have the effect we claimed, so the label is wrong; better to
learn that before scoring any detector against it.

Checks per expected event kind:
  restart     journal: the unit was started again (after stop/exit) near the expected time
  gap         monitoring: longest silence of the subsystem (or module) in the window vs. its
              normal message interval
  traceback   journal: a reassembled traceback from the unit in the window
  log_burst   logs: WARNING+ entries from the subsystem's server in the window vs. before it
  trend       monitoring: least-squares slope of the channel in the window vs. before it
"""

import json
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise
from pathlib import Path

from shiftassist.collect.journal import parse_journal
from shiftassist.collect.model import LEVELS, Entry
from shiftassist.collect.sstcam_logs import read_log_file
from shiftassist.sim.records import ExpectedEvent, Label
from shiftassist.sim.timeutil import parse_iso

NOMINAL_INTERVAL_S = 1.0  # every monitoring source (and each slow-signal module) sends at ~1 Hz
GAP_FACTOR = 5.0  # a silence longer than this many intervals counts as a gap
BURST_FACTOR = 10.0  # WARNING+ rate in the window this many times the rate before it
TREND_SIGMA = 5.0  # slope change significant at this many standard errors


@dataclass(frozen=True)
class Check:
    label_id: str
    event: ExpectedEvent
    found: bool | None  # None = inconclusive (window not covered by the capture)
    detail: str


class Capture:
    """Lazily loaded views of one capture directory."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._journal: list[Entry] | None = None
        self._logs: list[Entry] | None = None
        self._mon: dict[tuple[str, str], list[tuple[datetime, dict[str, float]]]] | None = None

    @property
    def journal(self) -> list[Entry]:
        if self._journal is None:
            with (self.path / "journal.jsonl").open() as fh:
                self._journal = list(parse_journal(fh))
        return self._journal

    @property
    def logs(self) -> list[Entry]:
        if self._logs is None:
            self._logs = [
                e
                for f in sorted((self.path / "data" / "logs").glob("log_*.txt"))
                if "gatherer_serve" not in f.name
                for e in read_log_file(f)
            ]
        return self._logs

    @property
    def monitoring(self) -> dict[tuple[str, str], list[tuple[datetime, dict[str, float]]]]:
        """(subsystem, entity) -> time-ordered (timestamp, top-level numeric fields)."""
        if self._mon is None:
            mon: dict[tuple[str, str], list[tuple[datetime, dict[str, float]]]] = defaultdict(list)
            with (self.path / "monitoring.jsonl").open() as fh:
                for line in fh:
                    d = json.loads(line)
                    ent = f"tm{int(d['tm_slot']):02d}" if "tm_slot" in d else ""
                    vals = {
                        k: float(v)
                        for k, v in d.items()
                        if isinstance(v, int | float) and not isinstance(v, bool)
                    }
                    mon[(d["subsystem"], ent)].append((parse_iso(d["timestamp"]), vals))
            for series in mon.values():
                series.sort(key=lambda x: x[0])
            self._mon = dict(mon)
        return self._mon

    @property
    def span(self) -> tuple[datetime, datetime]:
        """First and last monitoring timestamp: the time range this capture can speak about."""
        series = [s for s in self.monitoring.values() if s]
        return min(s[0][0] for s in series), max(s[-1][0] for s in series)

    def labels(self) -> list[Label]:
        with (self.path / "labels.jsonl").open() as fh:
            return [Label.model_validate_json(line) for line in fh if line.strip()]


def _window(label: Label, ev: ExpectedEvent) -> tuple[datetime, datetime]:
    """From just before the expected time (or the fault start) to the fault end + tolerance."""
    near, tol = parse_iso(ev.near), timedelta(seconds=ev.tolerance_s)
    start, end = parse_iso(label.start), parse_iso(label.end)
    return min(start, near - tol), max(end, near) + tol


def _unit(subsystem: str) -> str:
    return f"sstcam-{subsystem}.service"


def check_restart(cap: Capture, label: Label, ev: ExpectedEvent) -> Check:
    a, b = _window(label, ev)
    evs = [
        e
        for e in cap.journal
        if e.kind == "unit" and e.unit == _unit(ev.subsystem) and a <= e.ts <= b
    ]
    kinds = [e.fields.get("event") for e in evs]
    down = sum(k in ("exited", "stopped", "failed") for k in kinds)
    up = kinds.count("started")
    return Check(
        label.label_id,
        ev,
        down > 0 and up > 0,
        f"{down} stop/exit, {up} start in window ({', '.join(sorted(set(map(str, kinds))))})",
    )


def check_gap(cap: Capture, label: Label, ev: ExpectedEvent) -> Check:
    a, b = _window(label, ev)
    keys = [
        k
        for k in cap.monitoring
        if k[0] == ev.subsystem and (ev.entity is None or k[1] == ev.entity)
    ]
    if not keys:
        return Check(label.label_id, ev, False, "no monitoring for this source at all")
    worst = 0.0
    for k in keys:
        lo = a - timedelta(seconds=10)
        edges = [lo, *(t for t, _ in cap.monitoring[k] if lo <= t <= b), b]  # time-ordered
        worst = max(worst, max((y - x).total_seconds() for x, y in pairwise(edges)))
    found = worst > GAP_FACTOR * NOMINAL_INTERVAL_S
    return Check(
        label.label_id,
        ev,
        found,
        f"longest silence {worst:.1f} s (normal {NOMINAL_INTERVAL_S:.0f} s)",
    )


def check_traceback(cap: Capture, label: Label, ev: ExpectedEvent) -> Check:
    a, b = _window(label, ev)
    tbs = [
        e
        for e in cap.journal
        if e.kind == "traceback" and e.unit == _unit(ev.subsystem) and a <= e.ts <= b
    ]
    exc = sorted({e.fields.get("exception", "?") for e in tbs})
    return Check(label.label_id, ev, bool(tbs), f"{len(tbs)} traceback(s) {exc}")


def check_log_burst(cap: Capture, label: Label, ev: ExpectedEvent) -> Check:
    a, b = parse_iso(label.start), parse_iso(label.end) + timedelta(seconds=5)
    span = (b - a).total_seconds()
    proc = f"{ev.subsystem.upper()}-SERVER"
    warn = [e for e in cap.logs if e.process == proc and e.levelno >= LEVELS["WARNING"]]
    inside = sum(a <= e.ts <= b for e in warn)
    before = sum(a - timedelta(seconds=span) <= e.ts < a for e in warn)
    rate_in, rate_before = inside / span, before / span
    found = inside >= 10 and rate_in >= BURST_FACTOR * max(rate_before, 1 / span)
    return Check(
        label.label_id,
        ev,
        found,
        f"{inside} WARNING+ in window ({rate_in:.2f}/s) vs {before} before ({rate_before:.2f}/s)",
    )


def _slope_per_h(points: list[tuple[datetime, float]]) -> tuple[float, float]:
    """Least-squares slope (units per hour) and its standard error."""
    if len(points) < 3:
        return 0.0, float("inf")
    t0 = points[0][0]
    xs = [(t - t0).total_seconds() / 3600 for t, _ in points]
    ys = [y for _, y in points]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return 0.0, float("inf")
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx
    resid = [y - (my + slope * (x - mx)) for x, y in zip(xs, ys, strict=True)]
    se = (sum(r * r for r in resid) / max(len(xs) - 2, 1) / sxx) ** 0.5
    return slope, se


def check_trend(cap: Capture, label: Label, ev: ExpectedEvent) -> Check:
    start, end = parse_iso(label.start), parse_iso(label.end)
    series = cap.monitoring.get((ev.subsystem, ev.entity or ""), [])
    ch = ev.channel or ""
    inside = [(t, v[ch]) for t, v in series if start <= t <= end and ch in v]
    span = end - start
    before = [(t, v[ch]) for t, v in series if start - span <= t < start and ch in v]
    s_in, se_in = _slope_per_h(inside)
    s_b, se_b = _slope_per_h(before)
    z = abs(s_in - s_b) / max((se_in**2 + se_b**2) ** 0.5, 1e-12)
    return Check(
        label.label_id,
        ev,
        z >= TREND_SIGMA and len(inside) >= 10,
        f"{ch}: slope {s_in:+.2f}/h in window vs {s_b:+.2f}/h before (z={z:.1f}, n={len(inside)})",
    )


CHECKS = {
    "restart": check_restart,
    "gap": check_gap,
    "traceback": check_traceback,
    "log_burst": check_log_burst,
    "trend": check_trend,
}


def shift_label(label: Label, seconds: float) -> Label:
    """The same label moved in time (for negative controls on a fault-free capture)."""
    from shiftassist.sim.timeutil import iso as _iso

    def mv(ts: str) -> str:
        t = parse_iso(ts) + timedelta(seconds=seconds)
        return _iso(t, 0)

    return label.model_copy(
        update={
            "start": mv(label.start),
            "end": mv(label.end),
            "expected_events": [
                e.model_copy(update={"near": mv(e.near)}) for e in label.expected_events
            ],
        }
    )


def verify(capture: str | Path, labels: list[Label] | None = None) -> list[Check]:
    cap = Capture(capture)
    first, last = cap.span
    out: list[Check] = []
    for label in labels if labels is not None else cap.labels():
        for ev in label.expected_events:
            a, b = _window(label, ev)
            if a < first or b > last:
                out.append(
                    Check(
                        label.label_id,
                        ev,
                        None,
                        f"window {a:%H:%M:%S}-{b:%H:%M:%S} outside the capture "
                        f"({first:%H:%M:%S}-{last:%H:%M:%S}): inconclusive",
                    )
                )
                continue
            fn = CHECKS.get(ev.kind)
            out.append(
                fn(cap, label, ev)
                if fn
                else Check(label.label_id, ev, False, f"no check for kind {ev.kind!r}")
            )
    return out


def render(checks: list[Check]) -> str:
    rows = ["| label | expected | source | found | evidence |", "|---|---|---|:-:|---|"]
    for c in checks:
        src = c.event.subsystem + (f"/{c.event.entity}" if c.event.entity else "")
        mark = "⚪" if c.found is None else ("✅" if c.found else "❌")
        rows.append(f"| {c.label_id} | {c.event.kind} | {src} | {mark} | {c.detail} |")
    n_ok = sum(c.found is True for c in checks)
    n_na = sum(c.found is None for c in checks)
    head = f"**{n_ok}/{len(checks) - n_na} expected events have evidence in the capture**"
    head += f" ({n_na} inconclusive: window outside the capture)." if n_na else "."
    return head + "\n\n" + "\n".join(rows) + "\n"
