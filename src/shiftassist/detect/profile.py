"""Learn what "normal" looks like from clean captures (thresholds come from data, not guesses).

Several clean captures are pooled. Every threshold is at least the largest value seen in them
times a margin, with a floor, so that by construction the baselines themselves produce no alarm.

Trend thresholds also have a spread term, z x the robust standard deviation of the window slopes
(v1). The largest value in a baseline grows with the baseline's length, so a max-based threshold
learned from a short run is exceeded by a long one (X-15c); the spread does not grow. z is fixed
from the number of windows tested per hour and a target false-alarm rate, not tuned on data.
Whether that generalises is measured on a held-out clean capture (false alarms per hour).
"""

from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel

from shiftassist.collect.evidence import Capture
from shiftassist.collect.model import LEVELS
from shiftassist.collect.summary import template
from shiftassist.detect.series import common_mode_residuals, load_series, window_slopes

COMMON_MODE_SUBSYSTEMS = ("slowsignal",)  # many entities sharing the same environment


class Params(BaseModel):
    gap_factor: float = 5.0  # silence > this x median interval ...
    gap_max_factor: float = 2.0  # ... and > this x the longest interval seen in the baseline
    gap_floor_s: float = 5.0
    group_fraction: float = 0.5  # module gaps starting together on ≥ this share → one event
    group_window_s: float = 5.0
    trend_window_s: float = 180.0
    trend_step_s: float = 30.0
    trend_margin: float = 1.5  # threshold = margin x largest baseline |slope| ...
    trend_floor_per_h: float = 0.5  # ... but never below this
    trend_z: float = 5.0  # ... nor below z x robust sigma of baseline slopes (0 = v0 behaviour)
    trend_consecutive: int = 2  # windows above threshold in a row
    burst_window_s: float = 60.0
    burst_min_count: int = 10
    burst_factor: float = 10.0  # x baseline WARNING+ rate
    restart_coalesce_s: float = 120.0
    stall_factor: float = 2.0  # gatherer write silence > this x longest baseline write gap ...
    stall_floor_s: float = 5.0  # ... and > this
    late_factor: float = 2.0  # a message is late if written > this x the baseline's worst ...
    late_floor_s: float = 1.0  # ... and > this after its own timestamp


class SourceProfile(BaseModel):
    interval_median_s: float
    interval_max_s: float
    messages: int

    def gap_threshold(self, p: Params) -> float:
        return max(
            p.gap_factor * self.interval_median_s,
            p.gap_max_factor * self.interval_max_s,
            p.gap_floor_s,
        )


class TrendProfile(BaseModel):
    baseline_max_abs_per_h: float
    sigma_per_h: float | None = None  # 1.4826 x MAD of the window slopes (v1)
    threshold_per_h: float
    windows: int
    entities: int
    residual: bool  # computed on common-mode residuals


class Profile(BaseModel):
    learned_from: str
    duration_s: float
    params: Params
    sources: dict[str, SourceProfile]  # 'subsystem/entity'
    trend: dict[str, TrendProfile]  # 'subsystem/channel'
    warn_per_min: dict[str, float]  # process -> WARNING+ entries per minute
    known_templates: list[str]  # 'process|level|template' and 'traceback|unit|exception'
    write_gap_max_s: float | None = None  # longest gap between gatherer writes (all sources)
    late_max_s: float | None = None  # longest receive-minus-source delay in the baseline

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.model_dump_json(indent=2))

    @classmethod
    def load(cls, path: str | Path) -> "Profile":
        return cls.model_validate_json(Path(path).read_text())


def signature(process: str, level: str, message: str) -> str:
    return f"{process}|{level}|{template(message)}"


def robust_sigma(x: npt.NDArray[np.float64]) -> float:
    return float(1.4826 * np.median(np.abs(x - np.median(x)))) if len(x) else 0.0


def learn(captures: str | Path | list[str | Path], params: Params | None = None) -> Profile:
    """Pool one or more clean captures. Each capture is analysed on its own (intervals, slopes,
    residuals never span two captures); the statistics are then pooled."""
    p = params or Params()
    caps = [Capture(c) for c in (captures if isinstance(captures, list) else [captures])]
    duration = 0.0
    intervals: dict[str, list[npt.NDArray[np.float64]]] = defaultdict(list)
    slopes: dict[str, list[float]] = defaultdict(list)
    ents: dict[str, set[str]] = defaultdict(set)
    warn: Counter[str] = Counter()
    known: set[str] = set()
    write_gap: list[float] = []
    late_max: list[float] = []
    for cap in caps:
        first, last = cap.span
        duration += (last - first).total_seconds()
        times, series = load_series(cap)
        for (sub, ent), t in times.items():
            if len(t) >= 10:
                intervals[f"{sub}/{ent}"].append(np.diff(t))
        residuals = {}
        for sub in COMMON_MODE_SUBSYSTEMS:
            residuals.update(common_mode_residuals(series, sub))
        for key, sr in series.items():
            sub, ent, ch = key
            if np.ptp(sr.y) == 0:  # flat channel: no signal to trend on (R15)
                continue
            use = residuals.get(key, sr) if sub in COMMON_MODE_SUBSYSTEMS else sr
            _, sl = window_slopes(use, p.trend_window_s, p.trend_step_s)
            if len(sl):
                slopes[f"{sub}/{ch}"].extend(sl.tolist())
                ents[f"{sub}/{ch}"].add(ent)
        warn.update(e.process for e in cap.logs if e.levelno >= LEVELS["WARNING"])
        known |= {
            signature(e.process, e.level, e.message)
            for e in cap.logs
            if e.levelno >= LEVELS["WARNING"]
        }
        known |= {
            f"traceback|{e.unit}|{e.fields.get('exception')}"
            for e in cap.journal
            if e.kind == "traceback"
        }
        w = np.array([g.timestamp() for g, _, _ in cap.gathered])
        if len(w) > 1:
            write_gap.append(float(np.diff(w).max()))
            late_max.append(float((w - [t.timestamp() for _, t, _ in cap.gathered]).max()))

    sources = {}
    for src, ds in intervals.items():
        d = np.concatenate(ds)
        sources[src] = SourceProfile(
            interval_median_s=float(np.median(d)),
            interval_max_s=float(d.max()),
            messages=len(d) + len(ds),
        )
    trend = {}
    for fam, v in slopes.items():
        a = np.array(v)
        sig = robust_sigma(a)
        trend[fam] = TrendProfile(
            baseline_max_abs_per_h=float(np.abs(a).max()),
            sigma_per_h=sig,
            threshold_per_h=max(
                p.trend_margin * float(np.abs(a).max()), p.trend_z * sig, p.trend_floor_per_h
            ),
            windows=len(a),
            entities=len(ents[fam]),
            residual=fam.split("/")[0] in COMMON_MODE_SUBSYSTEMS,
        )
    # a capture exported without receive times gives no bound; do not guess one from the others
    have_rx = len(write_gap) == len(caps)
    return Profile(
        learned_from="+".join(c.path.name for c in caps),
        duration_s=duration,
        params=p,
        sources=sources,
        trend=trend,
        warn_per_min={k: v / (duration / 60) for k, v in warn.items()},
        known_templates=sorted(known),
        write_gap_max_s=max(write_gap) if have_rx else None,
        late_max_s=max(late_max) if have_rx else None,
    )
