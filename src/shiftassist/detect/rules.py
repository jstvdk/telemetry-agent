"""Detection rules. Each one reads the capture (never the labels) and yields events.

R-GAP-01    a monitoring source goes silent (per source; module gaps that start together on
            most modules become one subsystem-level event)
R-RST-01    a unit is started again after it stopped/exited/failed (a crash loop is one event)
R-TB-01     an uncaught traceback in the journal (same unit + exception coalesced)
R-BURST-01  WARNING+ entries from one process at a rate far above its baseline
R-SIG-01    a WARNING+ template or traceback exception never seen in the baseline
R-TRD-01    a value's slope over a sliding window exceeds the largest baseline slope x margin,
            in consecutive windows (slow-signal: on the module's deviation from the camera median)
"""

from collections import Counter, defaultdict
from collections.abc import Iterator
from datetime import UTC, datetime

import numpy as np

from shiftassist.collect.evidence import Capture
from shiftassist.collect.model import LEVELS, Entry
from shiftassist.collect.summary import template
from shiftassist.detect.model import Event
from shiftassist.detect.profile import COMMON_MODE_SUBSYSTEMS, Profile, signature
from shiftassist.detect.series import Key, Series, common_mode_residuals, load_series, window_slopes


def _dt(t: float) -> datetime:
    return datetime.fromtimestamp(t, UTC)


def _sub_of_unit(unit: str | None) -> str:
    u = unit or ""
    return u.removeprefix("sstcam-").removesuffix(".service")


def _sub_of_process(process: str) -> str:
    return process.lower().removesuffix("-server").removesuffix("-cli")


# --- R-GAP-01 ---------------------------------------------------------------------------------


def gaps(cap: Capture, prof: Profile, times: dict[tuple[str, str], np.ndarray]) -> Iterator[Event]:
    p = prof.params
    _, cap_end = cap.span
    raw: list[tuple[str, str, float, float | None, float]] = []  # sub, ent, start, end, thr
    for (sub, ent), t in times.items():
        sp = prof.sources.get(f"{sub}/{ent}")
        if sp is None or len(t) < 2:
            continue
        thr = sp.gap_threshold(p)
        edges = np.append(t, cap_end.timestamp())
        d = np.diff(edges)
        for gi in np.nonzero(d > thr)[0]:
            end = float(edges[gi + 1]) if gi + 1 < len(t) else None
            raw.append((sub, ent, float(edges[gi]), end, thr))

    by_sub: dict[str, list[tuple[str, str, float, float | None, float]]] = defaultdict(list)
    for r in raw:
        by_sub[r[0]].append(r)
    for sub, items in by_sub.items():
        n_ent = sum(1 for (s, _) in times if s == sub)
        items.sort(key=lambda r: r[2])
        used = [False] * len(items)
        for i, (_, ent, start, end, thr) in enumerate(items):
            if used[i]:
                continue
            group = [
                j
                for j in range(i, len(items))
                if not used[j] and items[j][2] - start <= p.group_window_s
            ]
            if n_ent > 1 and len(group) >= p.group_fraction * n_ent:
                for j in group:
                    used[j] = True
                ends = [items[j][3] for j in group]
                g_end = None if any(e is None for e in ends) else max(e for e in ends if e)
                yield _gap_event(cap, sub, None, start, g_end, thr, len(group), n_ent)
            else:
                used[i] = True
                yield _gap_event(cap, sub, ent or None, start, end, thr, 1, n_ent)


def _gap_event(
    cap: Capture,
    sub: str,
    ent: str | None,
    start: float,
    end: float | None,
    thr: float,
    n: int,
    n_ent: int,
) -> Event:
    dur = (end - start) if end else None
    who = f"{sub}" + (f" module {ent}" if ent else (f" ({n}/{n_ent} modules)" if n_ent > 1 else ""))
    how_long = f"{dur:.0f} s" if dur else "until the end of the capture"
    return Event(
        ts=_dt(start),
        end=_dt(end) if end else None,
        camera=cap.path.name,
        subsystem=sub,
        entity=ent,
        kind="gap",
        severity="alarm",
        rule_id="R-GAP-01",
        summary=f"No monitoring from {who} for {how_long} (normal gap < {thr:.1f} s)",
        evidence={"silence_s": dur, "threshold_s": thr, "entities": n},
    )


# --- R-RST-01 ---------------------------------------------------------------------------------


def restarts(cap: Capture, prof: Profile) -> Iterator[Event]:
    by_unit: dict[str, list[Entry]] = defaultdict(list)
    for e in cap.journal:
        if e.kind == "unit" and e.unit and e.unit.endswith(".service"):
            by_unit[e.unit].append(e)
    for unit, evs in by_unit.items():
        episode: list[Entry] = []
        down: Entry | None = None
        for e in evs:
            ev = e.fields.get("event")
            if ev in ("exited", "stopped", "failed") and down is None:
                down = e
            elif ev == "started" and down is not None:
                if (
                    episode
                    and (down.ts - episode[-1].ts).total_seconds() > prof.params.restart_coalesce_s
                ):
                    yield _restart_event(cap, unit, episode)
                    episode = []
                episode += [down, e]
                down = None
        if episode:
            yield _restart_event(cap, unit, episode)


def _restart_event(cap: Capture, unit: str, ep: list[Entry]) -> Event:
    downs = ep[0::2]
    n = len(downs)
    crashed = [d for d in downs if d.fields.get("event") in ("exited", "failed")]
    codes = Counter(
        f"{d.fields.get('code')}/{d.fields.get('status')}" for d in crashed if d.fields.get("code")
    )
    how = ("crash loop: " if n >= 3 else "") + (
        f"{n} restart(s)" + (f", exits: {dict(codes)}" if codes else " after stop")
    )
    return Event(
        ts=downs[0].ts,
        end=ep[-1].ts,
        camera=cap.path.name,
        subsystem=_sub_of_unit(unit),
        kind="restart",
        severity="alarm" if crashed else "warning",
        rule_id="R-RST-01",
        summary=f"{unit}: {how}",
        evidence={"restarts": n, "refs": [x.ref for x in ep][:20], "exits": dict(codes)},
    )


# --- R-TB-01 / R-SIG-01 (tracebacks and new templates) -----------------------------------------


def tracebacks(cap: Capture, prof: Profile) -> Iterator[Event]:
    groups: dict[tuple[str, str], list[Entry]] = defaultdict(list)
    for e in cap.journal:
        if e.kind == "traceback":
            groups[(e.unit or "", str(e.fields.get("exception")))].append(e)
    for (unit, exc), tbs in groups.items():
        tbs.sort(key=lambda x: x.ts)
        episodes: list[list[Entry]] = [[tbs[0]]]
        for tb in tbs[1:]:
            if (tb.ts - episodes[-1][-1].ts).total_seconds() > prof.params.restart_coalesce_s:
                episodes.append([])
            episodes[-1].append(tb)
        for ep in episodes:
            line = str(ep[0].fields.get("exception_line", ""))[:200]
            yield Event(
                ts=ep[0].ts,
                end=ep[-1].ts,
                camera=cap.path.name,
                subsystem=_sub_of_unit(unit),
                kind="traceback",
                severity="alarm",
                rule_id="R-TB-01",
                summary=f"{unit}: {len(ep)} x {line}",
                evidence={"count": len(ep), "refs": [x.ref for x in ep][:10], "exception": exc},
            )


def new_signatures(cap: Capture, prof: Profile) -> Iterator[Event]:
    known = set(prof.known_templates)
    seen: set[str] = set()
    items: list[tuple[datetime, str, str, str, Entry]] = []
    for e in cap.logs:
        if e.levelno >= LEVELS["WARNING"]:
            items.append(
                (
                    e.ts,
                    signature(e.process, e.level, e.message),
                    _sub_of_process(e.process),
                    template(e.message),
                    e,
                )
            )
    for e in cap.journal:
        if e.kind == "traceback":
            items.append(
                (
                    e.ts,
                    f"traceback|{e.unit}|{e.fields.get('exception')}",
                    _sub_of_unit(e.unit),
                    str(e.fields.get("exception_line", "")),
                    e,
                )
            )
    for ts, sig, sub, text, e in sorted(items, key=lambda x: x[0]):
        if sig in known or sig in seen:
            continue
        seen.add(sig)
        yield Event(
            ts=ts,
            camera=cap.path.name,
            subsystem=sub,
            kind="new_signature",
            severity="warning",
            rule_id="R-SIG-01",
            summary=f"First occurrence of a message never seen in the baseline: {text[:140]}",
            evidence={"signature": sig, "ref": e.ref},
        )


# --- R-BURST-01 --------------------------------------------------------------------------------


def bursts(cap: Capture, prof: Profile) -> Iterator[Event]:
    p = prof.params
    by_proc: dict[str, list[Entry]] = defaultdict(list)
    for e in cap.logs:
        if e.levelno >= LEVELS["WARNING"]:
            by_proc[e.process].append(e)
    for proc, es in by_proc.items():
        base = prof.warn_per_min.get(proc, 0.0) * p.burst_window_s / 60
        thr = max(p.burst_min_count, p.burst_factor * base)
        t = np.array([e.ts.timestamp() for e in es])
        counts = np.searchsorted(t, t, side="right") - np.searchsorted(t, t - p.burst_window_s)
        hot = counts >= thr
        i = 0
        while i < len(es):
            if not hot[i]:
                i += 1
                continue
            j = i
            while j + 1 < len(es) and (hot[j + 1] or t[j + 1] - t[j] < p.burst_window_s / 2):
                j += 1
            # the burst began with the entries that made the first window hot
            k = int(np.searchsorted(t, t[i] - p.burst_window_s))
            chunk = es[k : j + 1]
            top = Counter(template(e.message) for e in chunk).most_common(1)[0]
            yield Event(
                ts=es[k].ts,
                end=es[j].ts,
                camera=cap.path.name,
                subsystem=_sub_of_process(proc),
                kind="log_burst",
                severity="warning",
                rule_id="R-BURST-01",
                summary=f"{proc}: {len(chunk)} WARNING+ entries in "
                f"{(t[j] - t[k]):.0f} s (baseline {base:.2f}/min); top: {top[0][:100]}",
                evidence={
                    "count": len(chunk),
                    "threshold_per_window": thr,
                    "first_ref": chunk[0].ref,
                    "top_template": top[0],
                },
            )
            i = j + 1


# --- R-TRD-01 -----------------------------------------------------------------------------------


def trends(cap: Capture, prof: Profile, series: dict[Key, Series]) -> Iterator[Event]:
    """Episodes of consecutive windows whose |slope| exceeds the baseline threshold. The event is
    stamped at detection time (end of the first hot window). If the same channel trends on most
    entities at once, that is a camera-wide change, reported as one subsystem-level event."""
    p = prof.params
    residuals: dict[Key, Series] = {}
    for sub in COMMON_MODE_SUBSYSTEMS:
        residuals.update(common_mode_residuals(series, sub))
    episodes: list[tuple[str, str, str, float, float, float, float, bool]] = []
    for key, s in series.items():
        sub, ent, ch = key
        tp = prof.trend.get(f"{sub}/{ch}")
        if tp is None:
            continue
        use = residuals.get(key) if tp.residual else s
        if use is None:
            continue
        te, sl = window_slopes(use, p.trend_window_s, p.trend_step_s)
        hot = np.abs(sl) > tp.threshold_per_h
        i = 0
        while i < len(hot):
            if not hot[i]:
                i += 1
                continue
            j = i
            while j + 1 < len(hot) and hot[j + 1] and te[j + 1] - te[j] <= 1.5 * p.trend_step_s:
                j += 1
            if j - i + 1 >= p.trend_consecutive:
                episodes.append(
                    (
                        sub,
                        ent,
                        ch,
                        float(te[i]),
                        float(te[j]),
                        float(sl[i]),
                        tp.threshold_per_h,
                        tp.residual,
                    )
                )
            i = j + 1

    ents_per_sub: dict[str, int] = defaultdict(int)
    for sub_, _ in {(k[0], k[1]) for k in series if k[1]}:
        ents_per_sub[sub_] += 1
    groups: dict[tuple[str, str, int], list[tuple[str, str, str, float, float, float, float, bool]]]
    groups = defaultdict(list)
    for (
        ep
    ) in episodes:  # bucket by (subsystem, channel, detection minute) to spot camera-wide changes
        groups[(ep[0], ep[2], int(ep[3] // 60))].append(ep)
    for (sub, ch, _), eps in groups.items():
        total = ents_per_sub.get(sub, 0)
        if total and len({e[1] for e in eps}) >= p.group_fraction * total:
            first = min(e[3] for e in eps)
            last = max(e[4] for e in eps)
            yield Event(
                ts=_dt(first),
                end=_dt(last),
                camera=cap.path.name,
                subsystem=sub,
                channel=ch,
                kind="trend",
                severity="info",
                rule_id="R-TRD-02",
                summary=f"{sub} {ch} changing on {len(eps)}/{total} modules at once "
                "(camera-wide, not a single module)",
                evidence={"modules": sorted({e[1] for e in eps})[:40]},
            )
            continue
        for sub_, ent, ch_, t_first, t_last, slope, thr, resid in eps:
            where = f"{sub_} {ent} " if ent else f"{sub_} "
            rel = " relative to the other modules" if resid else ""
            yield Event(
                ts=_dt(t_first),
                end=_dt(t_last),
                camera=cap.path.name,
                subsystem=sub_,
                entity=ent or None,
                channel=ch_,
                kind="trend",
                severity="warning",
                rule_id="R-TRD-01",
                summary=f"{where}{ch_} changing at {slope:+.2f}/h{rel} (threshold {thr:.2f}/h)",
                evidence={
                    "initial_slope_per_h": slope,
                    "threshold_per_h": thr,
                    "until": _dt(t_last).isoformat(),
                    "residual": resid,
                },
            )


def detect(capture: str, prof: Profile) -> list[Event]:
    cap = Capture(capture)
    times, series = load_series(cap)
    events = [
        *gaps(cap, prof, times),
        *restarts(cap, prof),
        *tracebacks(cap, prof),
        *new_signatures(cap, prof),
        *bursts(cap, prof),
        *trends(cap, prof, series),
    ]
    events.sort(key=lambda e: (e.ts, e.kind, e.subsystem, e.entity or ""))
    for n, e in enumerate(events, start=1):
        e.event_id = f"EV-{n:06d}"
    return events
