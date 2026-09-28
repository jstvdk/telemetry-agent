"""Monitoring as numpy series, and the windowed slope used by the trend rule."""

from collections import defaultdict
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from shiftassist.collect.evidence import Capture

Key = tuple[str, str, str]  # (subsystem, entity, channel)
F64 = npt.NDArray[np.float64]


@dataclass
class Series:
    t: F64  # seconds since epoch, sorted
    y: F64


def load_series(cap: Capture) -> tuple[dict[tuple[str, str], F64], dict[Key, Series]]:
    """Message times per source (subsystem, entity), and values per (subsystem, entity, channel)."""
    times: dict[tuple[str, str], F64] = {}
    series: dict[Key, Series] = {}
    for (sub, ent), msgs in cap.monitoring.items():
        t = np.array([ts.timestamp() for ts, _ in msgs], dtype=np.float64)
        times[(sub, ent)] = t
        cols: dict[str, list[float]] = defaultdict(list)
        tcols: dict[str, list[float]] = defaultdict(list)
        for (_, vals), tt in zip(msgs, t, strict=True):
            for ch, v in vals.items():
                cols[ch].append(v)
                tcols[ch].append(tt)
        for ch, ys in cols.items():
            series[(sub, ent, ch)] = Series(np.array(tcols[ch]), np.array(ys, dtype=np.float64))
    return times, series


def common_mode_residuals(series: dict[Key, Series], subsystem: str) -> dict[Key, Series]:
    """For a subsystem with many entities (slow-signal modules), remove what they share.

    Each module is first centred on its own median (modules have different fixed offsets), then
    the per-second median across the centred modules is subtracted. Centring first matters: with
    raw values, a module dropping out shifts the cross-module median by a fraction of the offset
    spread, which shows up as a step, and so as a false slope, in every other module.
    """
    out: dict[Key, Series] = {}
    channels = {k[2] for k in series if k[0] == subsystem and k[1]}
    for ch in channels:
        keys = [k for k in series if k[0] == subsystem and k[1] and k[2] == ch]
        if len(keys) < 5:
            continue
        centred = {k: series[k].y - float(np.median(series[k].y)) for k in keys}
        buckets: dict[int, list[float]] = defaultdict(list)
        for k in keys:
            for tt, yy in zip(series[k].t.astype(np.int64), centred[k], strict=True):
                buckets[int(tt)].append(float(yy))
        med = {b: float(np.median(v)) for b, v in buckets.items() if len(v) >= len(keys) // 2}
        for k in keys:
            s = series[k]
            m = np.array([med.get(int(tt), np.nan) for tt in s.t])
            ok = ~np.isnan(m)
            out[k] = Series(s.t[ok], centred[k][ok] - m[ok])
    return out


def window_slopes(
    s: Series, window_s: float, step_s: float, min_fill: float = 0.8, expected_rate_hz: float = 1.0
) -> tuple[F64, F64]:
    """Least-squares slope (units per hour) over trailing windows ending every ``step_s``.
    Windows with fewer than ``min_fill`` of the expected points are skipped.
    Returns (window end times, slopes)."""
    if len(s.t) < 3:
        return np.empty(0), np.empty(0)
    ends = np.arange(s.t[0] + window_s, s.t[-1] + 1e-9, step_s)
    need = min_fill * window_s * expected_rate_hz
    lo = np.searchsorted(s.t, ends - window_s, side="left")
    hi = np.searchsorted(s.t, ends, side="right")
    out_t, out_s = [], []
    for e, a, b in zip(ends, lo, hi, strict=True):
        if b - a < max(need, 3):
            continue
        x = (s.t[a:b] - s.t[a]) / 3600.0
        y = s.y[a:b]
        xm = x - x.mean()
        sxx = float(xm @ xm)
        if sxx == 0:
            continue
        out_t.append(e)
        out_s.append(float(xm @ (y - y.mean())) / sxx)
    return np.array(out_t), np.array(out_s)
