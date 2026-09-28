"""Detection output: events with IDs and code-written evidence (the timeline the LLM reads)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from shiftassist.sim.records import EventKind

Severity = Literal["info", "warning", "alarm"]


class Event(BaseModel):
    event_id: str = ""  # assigned after sorting: 'EV-000001'
    ts: datetime  # when the anomaly started (first evidence)
    end: datetime | None = None  # when it ended, if it did within the capture
    camera: str
    subsystem: str
    entity: str | None = None  # e.g. 'tm07' for a slow-signal module
    channel: str | None = None  # for value rules
    kind: EventKind
    severity: Severity
    rule_id: str  # which rule fired, e.g. 'R-GAP-01'
    summary: str  # one line, written by code, not by the LLM
    evidence: dict[str, Any] = {}  # numbers and references (Entry.ref) that back the summary
