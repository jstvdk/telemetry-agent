"""What the simulator produces: stream records (logs, telemetry) and ground-truth labels.

Records carry integer-millisecond offsets internally and are serialised with absolute
ISO-8601 UTC timestamps. Labels are the contract with the evaluation harness.
"""

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

Level = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
EventKind = Literal[
    "limit",  # a value crossed a threshold
    "trend",  # a value drifts (rate of change), no threshold crossed yet
    "gap",  # expected data stopped arriving (monitoring silence, missing heartbeats)
    "restart",  # a process stopped/exited and was started again
    "config_change",
    "traceback",
    "new_signature",  # an error message template never seen before
    "log_burst",  # a message template suddenly repeats at a high rate
]


@dataclass(frozen=True, slots=True)
class LogRecord:
    t_ms: int
    camera: str
    subsystem: str
    level: Level
    text: str  # may be multi-line (tracebacks)


@dataclass(frozen=True, slots=True)
class TelemetryRecord:
    t_ms: int
    camera: str
    channel: str  # '<subsystem>.<name>_<unit>', e.g. 'cooling.plate_temp_c'
    value: float


Record = LogRecord | TelemetryRecord


def subsystem_of(record: Record) -> str:
    return record.subsystem if isinstance(record, LogRecord) else record.channel.split(".", 1)[0]


class ExpectedEvent(BaseModel):
    """An event the deterministic detection layer must produce for this label."""

    kind: EventKind
    camera: str
    subsystem: str
    near: str  # ISO-8601 UTC
    tolerance_s: float
    channel: str | None = None
    entity: str | None = None  # sub-device, e.g. 'tm07' (slow-signal module)


class Label(BaseModel):
    """Ground truth for one injected fault on one camera."""

    label_id: str  # '<scenario>-L<nn>'
    scenario: str
    fault_index: int  # position in the scenario's fault list
    group: str  # same value for one fault applied to several cameras (common cause)
    kind: str  # fault kind, e.g. 'readout_crash'
    camera: str
    subsystem: str
    start: str
    end: str
    root_cause: str
    expected_events: list[ExpectedEvent]
    details: dict[str, Any] = {}
