"""Mutable state shared by the nominal generator and the fault injectors during one run."""

import math
import random
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from shiftassist.sim.nominal import CHANNELS, nominal_series
from shiftassist.sim.records import EventKind, ExpectedEvent, Label, Level, LogRecord
from shiftassist.sim.scenario import Scenario
from shiftassist.sim.timeutil import iso


@dataclass(frozen=True, slots=True)
class Blackout:
    """Records suppressed in [t0, t1). Fault-generated logs are never suppressed."""

    camera: str
    t0: int
    t1: int
    subsystems: frozenset[str] | None  # None = all subsystems
    telemetry: bool  # also drop telemetry samples (a real gap, not a zero value)


class SimContext:
    def __init__(self, scenario: Scenario, seed: int) -> None:
        self.scenario = scenario
        self.seed = seed
        self.duration_ms = scenario.duration_ms
        self.interval_ms = scenario.telemetry_interval_ms
        self.grid: list[int] = list(range(0, self.duration_ms, self.interval_ms))
        self.tm: dict[tuple[str, str], list[float]] = {}
        self.fault_logs: list[LogRecord] = []
        self.blackouts: list[Blackout] = []
        self.labels: list[Label] = []
        for cam in scenario.cameras:
            for ch, model in CHANNELS.items():
                self.tm[(cam, ch)] = nominal_series(model, self.grid, self.rng("tm", cam, ch))

    # --- randomness -------------------------------------------------------------------------
    def rng(self, *parts: object) -> random.Random:
        """Independent, reproducible stream per component (str seeds are hash-seed independent)."""
        return random.Random(":".join(str(p) for p in (self.seed, *parts)))

    # --- time -------------------------------------------------------------------------------
    def iso(self, t_ms: int) -> str:
        return iso(self.scenario.start, t_ms)

    def clamp(self, t_ms: int) -> int:
        return max(0, min(t_ms, self.duration_ms - 1))

    # --- telemetry --------------------------------------------------------------------------
    def _indices(self, t0: int, t1: int) -> range:
        lo = max(0, math.ceil(t0 / self.interval_ms))
        hi = min(len(self.grid), math.ceil(t1 / self.interval_ms))
        return range(lo, hi)

    def apply(
        self, camera: str, channel: str, t0: int, t1: int, fn: Callable[[int, float], float]
    ) -> None:
        """Replace samples in [t0, t1) with fn(t_ms, current_value)."""
        series = self.tm[(camera, channel)]
        for i in self._indices(t0, t1):
            series[i] = fn(self.grid[i], series[i])

    def value_at(self, camera: str, channel: str, t_ms: int) -> float:
        i = min(max(0, t_ms // self.interval_ms), len(self.grid) - 1)
        return self.tm[(camera, channel)][i]

    # --- logs, blackouts, labels ------------------------------------------------------------
    def log(self, t_ms: int, camera: str, subsystem: str, level: Level, text: str) -> None:
        self.fault_logs.append(LogRecord(self.clamp(t_ms), camera, subsystem, level, text))

    def blackout(
        self,
        camera: str,
        t0: int,
        t1: int,
        subsystems: Iterable[str] | None = None,
        telemetry: bool = False,
    ) -> None:
        subs = frozenset(subsystems) if subsystems is not None else None
        self.blackouts.append(Blackout(camera, t0, t1, subs, telemetry))

    def expect(
        self,
        kind: EventKind,
        camera: str,
        subsystem: str,
        t_ms: int,
        tolerance_s: float,
        channel: str | None = None,
    ) -> ExpectedEvent:
        return ExpectedEvent(
            kind=kind,
            camera=camera,
            subsystem=subsystem,
            near=self.iso(self.clamp(t_ms)),
            tolerance_s=tolerance_s,
            channel=channel,
        )

    def label(
        self,
        *,
        fault_index: int,
        kind: str,
        camera: str,
        subsystem: str,
        t0: int,
        t1: int,
        root_cause: str,
        expected: list[ExpectedEvent],
        details: dict[str, Any] | None = None,
    ) -> None:
        self.labels.append(
            Label(
                label_id=f"{self.scenario.id}-L{len(self.labels) + 1:02d}",
                scenario=self.scenario.id,
                fault_index=fault_index,
                group=f"{self.scenario.id}-F{fault_index:02d}",
                kind=kind,
                camera=camera,
                subsystem=subsystem,
                start=self.iso(self.clamp(t0)),
                end=self.iso(self.clamp(t1)),
                root_cause=root_cause,
                expected_events=expected,
                details=details or {},
            )
        )
