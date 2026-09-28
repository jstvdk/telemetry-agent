"""What collectors produce: log entries (text, with a citable reference) and telemetry samples."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

# Python logging levels plus the camera server's two custom ones (SUCCESS = INFO+5,
# VERBOSE = DEBUG-5).
LEVELS: dict[str, int] = {
    "VERBOSE": 5,
    "DEBUG": 10,
    "INFO": 20,
    "SUCCESS": 25,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}

EntryKind = Literal[
    "log",  # a record written by the application's logger
    "unit",  # a systemd lifecycle message about a unit (started, exited, restart scheduled, ...)
    "traceback",  # an uncaught exception, reassembled from raw stdout/stderr lines
    "stdout",  # any other raw process output
]


@dataclass(frozen=True, slots=True)
class Entry:
    ts: datetime  # timezone-aware, UTC
    source: str  # e.g. 'log/log_20260928T182543_sstcam_chiller_serve.txt', 'central/…', 'journal'
    line: int  # first line (files) or record index (journal) of this entry in its source
    kind: EntryKind
    level: str
    process: str  # camera process name ('CHILLER-SERVER') or systemd unit for raw output
    logger: str  # 'package.context' (pipe), 'path:lineno func' (central), '' otherwise
    message: str  # full text; continuation lines joined with '\n'
    unit: str | None = None
    pid: int | None = None
    fields: dict[str, Any] = field(default_factory=dict)

    @property
    def levelno(self) -> int:
        return LEVELS.get(self.level, 0)

    @property
    def ref(self) -> str:
        """Stable citation handle: where to find this entry in the capture."""
        return f"{self.source}:{self.line}"


@dataclass(frozen=True, slots=True)
class Sample:
    ts: datetime
    subsystem: str  # 'chiller', 'slowboard', 'slowsignal', 'eventbuilder', ...
    entity: str  # sub-device, e.g. 'tm07' for a slow-signal module; '' if none
    channel: str  # dotted path inside the message, e.g. 'fans_1.speeds.3'
    value: float
