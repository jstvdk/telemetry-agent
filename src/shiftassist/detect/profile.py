"""Learn what "normal" looks like from one clean capture (thresholds come from data, not guesses).

Every threshold is the largest value seen in the clean baseline times a margin, with a floor, so
that by construction the baseline itself produces no alarm. Whether that generalises is measured
on a second, held-out clean capture (false alarms per hour).
"""

from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
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
    trend_consecutive: int = 2  # windows above threshold in a row
    burst_window_s: float = 60.0
    burst_min_count: int = 10
    burst_factor: float = 10.0  # x baseline WARNING+ rate
    restart_coalesce_s: float = 120.0


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

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.model_dump_json(indent=2))

    @classmethod
    def load(cls, path: str | Path) -> "Profile":
        return cls.model_validate_json(Path(path).read_text())


def signature(process: str, level: str, message: str) -> str:
    return f"{process}|{level}|{template(message)}"


def learn(capture: str | Path, params: Params | None = None) -> Profile:
    p = params or Params()
    cap = Capture(capture)
    first, last = cap.span
    duration = (last - first).total_seconds()
    times, series = load_series(cap)

    sources: dict[str, SourceProfile] = {}
    for (sub, ent), t in times.items():
        if len(t) < 10:
            continue
        d = np.diff(t)
        sources[f"{sub}/{ent}"] = SourceProfile(
            interval_median_s=float(np.median(d)), interval_max_s=float(d.max()), messages=len(t)
        )

    residuals = {}
    for sub in COMMON_MODE_SUBSYSTEMS:
        residuals.update(common_mode_residuals(series, sub))
    slopes: dict[str, list[float]] = defaultdict(list)
    ents: dict[str, set[str]] = defaultdict(set)
    for key, s in series.items():
        sub, ent, ch = key
        if np.ptp(s.y) == 0:  # flat channel: no signal to trend on (R15)
            continue
        use = residuals.get(key, s) if sub in COMMON_MODE_SUBSYSTEMS else s
        _, sl = window_slopes(use, p.trend_window_s, p.trend_step_s)
        if len(sl):
            slopes[f"{sub}/{ch}"].extend(np.abs(sl).tolist())
            ents[f"{sub}/{ch}"].add(ent)
    trend = {
        fam: TrendProfile(
            baseline_max_abs_per_h=max(v),
            threshold_per_h=max(p.trend_margin * max(v), p.trend_floor_per_h),
            windows=len(v),
            entities=len(ents[fam]),
            residual=fam.split("/")[0] in COMMON_MODE_SUBSYSTEMS,
        )
        for fam, v in slopes.items()
    }

    warn = Counter(e.process for e in cap.logs if e.levelno >= LEVELS["WARNING"])
    known = {
        signature(e.process, e.level, e.message) for e in cap.logs if e.levelno >= LEVELS["WARNING"]
    }
    known |= {
        f"traceback|{e.unit}|{e.fields.get('exception')}"
        for e in cap.journal
        if e.kind == "traceback"
    }
    return Profile(
        learned_from=Path(capture).name,
        duration_s=duration,
        params=p,
        sources=sources,
        trend=trend,
        warn_per_min={k: v / (duration / 60) for k, v in warn.items()},
        known_templates=sorted(known),
    )
