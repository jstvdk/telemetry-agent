"""A frozen view of one camera for the LLM layer: capture + detector events + profile + runbook.

The snapshot is the unit of evaluation: the same snapshot and question always give the tools the
same answers. Nothing here writes. Relative windows ("the last 30 minutes") are measured from the
newest record in the snapshot, not from the wall clock.
"""

from datetime import datetime, timedelta
from pathlib import Path

from shiftassist.collect.evidence import Capture
from shiftassist.collect.model import Entry
from shiftassist.detect.model import Event
from shiftassist.detect.profile import COMMON_MODE_SUBSYSTEMS, Profile
from shiftassist.detect.series import Key, Series, common_mode_residuals, load_series
from shiftassist.sim.timeutil import parse_iso
from shiftassist.tools.runbook import Runbook

DEFAULT_RUNBOOK = Path(__file__).resolve().parents[3] / "runbook"


class Snapshot:
    def __init__(
        self,
        capture: str | Path,
        events: str | Path | None = None,
        profile: str | Path | None = None,
        runbook: str | Path | Runbook | None = DEFAULT_RUNBOOK,
    ):
        self.cap = Capture(capture)
        ev_path = Path(events) if events else self.cap.path / "events.jsonl"
        self.events = [
            Event.model_validate_json(x) for x in ev_path.read_text().splitlines() if x.strip()
        ]
        self.by_id = {e.event_id: e for e in self.events}
        self.profile = Profile.load(profile) if profile else None
        if isinstance(runbook, Runbook) or runbook is None:
            self.runbook = runbook or Runbook([])
        else:
            self.runbook = Runbook.load(runbook)
        self.start, self.end = self.cap.span
        self._refs: dict[str, Entry] | None = None
        self._series: dict[Key, Series] | None = None
        self._residuals: dict[Key, Series] | None = None

    @property
    def camera(self) -> str:
        return self.cap.path.name

    def entry(self, ref: str) -> Entry | None:
        if self._refs is None:
            self._refs = {e.ref: e for e in [*self.cap.journal, *self.cap.logs]}
        return self._refs.get(ref)

    @property
    def series(self) -> dict[Key, Series]:
        if self._series is None:
            _, self._series = load_series(self.cap)
        return self._series

    @property
    def residuals(self) -> dict[Key, Series]:
        """Per-module deviation from the camera-wide median (as the trend rule uses)."""
        if self._residuals is None:
            self._residuals = {}
            for sub in COMMON_MODE_SUBSYSTEMS:
                self._residuals.update(common_mode_residuals(self.series, sub))
        return self._residuals

    def window(
        self, start: str | None, end: str | None, since_minutes: float | None
    ) -> tuple[datetime, datetime]:
        """Explicit ISO times win; else the last ``since_minutes``; else the whole snapshot."""
        b = parse_iso(end) if end else self.end
        if start:
            a = parse_iso(start)
        elif since_minutes is not None:
            a = b - timedelta(minutes=since_minutes)
        else:
            a = self.start
        return a, b
