"""Parse a systemd journal export (``journalctl -o json``) into entries.

Three kinds of journal records matter for the camera:

1. systemd's own messages about a unit ("Started …", "Main process exited, code=killed,
   status=9/KILL", "Scheduled restart job, restart counter is at 3") → kind 'unit', with the
   lifecycle event in ``fields['event']``.
2. Service stdout lines in the camera's pipe format: the same records the per-process log file
   holds → kind 'log', ``fields['mirror'] = True`` so they can be de-duplicated.
3. Any other stdout: in practice uncaught-exception tracebacks, which reach **only** the journal
   (never the log files) and arrive one line per record at priority INFO → reassembled per PID
   into one kind='traceback' entry at level ERROR.
"""

import json
import re
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from typing import Any

from shiftassist.collect.model import Entry
from shiftassist.collect.sstcam_logs import PIPE

_UNIT_EVENTS: list[tuple[str, re.Pattern[str]]] = [
    ("started", re.compile(r"^Started ")),
    ("stopping", re.compile(r"^Stopping ")),
    ("stopped", re.compile(r"^Stopped ")),
    ("exited", re.compile(r"Main process exited, code=(?P<code>\w+), status=(?P<status>\S+)")),
    (
        "control_failed",
        re.compile(r"Control process exited, code=(?P<code>\w+), status=(?P<status>\S+)"),
    ),
    ("failed", re.compile(r"Failed with result '(?P<result>[^']+)'")),
    ("restart_scheduled", re.compile(r"Scheduled restart job, restart counter is at (?P<n>\d+)")),
    ("start_limit", re.compile(r"Start request repeated too quickly")),
]
_TB_START = "Traceback (most recent call last):"
_TB_CHAIN = (
    "During handling of the above exception, another exception occurred:",
    "The above exception was the direct cause of the following exception:",
)
_PRIORITY = {
    0: "CRITICAL",
    1: "CRITICAL",
    2: "CRITICAL",
    3: "ERROR",
    4: "WARNING",
    5: "INFO",
    6: "INFO",
    7: "DEBUG",
}


def _text(v: Any) -> str:
    if isinstance(v, list):  # journald exports non-UTF-8 / binary messages as byte arrays
        return bytes(v).decode("utf-8", errors="replace")
    return "" if v is None else str(v)


def _ts(rec: dict[str, Any]) -> datetime:
    return datetime.fromtimestamp(int(rec["__REALTIME_TIMESTAMP"]) / 1e6, tz=UTC)


def _unit_event(msg: str) -> tuple[str, dict[str, Any]] | None:
    body = msg.split(": ", 1)[1] if msg.startswith("sstcam") and ": " in msg else msg
    for name, rx in _UNIT_EVENTS:
        m = rx.search(body)
        if m:
            return name, {k: v for k, v in m.groupdict().items() if v is not None}
    return None


class _Traceback:
    def __init__(self, rec: dict[str, Any], index: int, unit: str | None, pid: int | None):
        self.ts, self.index, self.unit, self.pid = _ts(rec), index, unit, pid
        self.lines: list[str] = []
        self.done = False  # exception line seen; only a chain marker can reopen it

    def feed(self, line: str) -> bool:
        """Consume one line if it belongs to this traceback. A block ends at its exception line
        ('ExcType: message', not indented); a blank line or a chain marker after it continues
        with the next chained block."""
        if not self.done:
            self.lines.append(line)
            if line and not line[0].isspace() and line != _TB_START and line not in _TB_CHAIN:
                self.done = True
            return True
        if line == "":
            self.lines.append(line)
            return True
        if line in _TB_CHAIN or line == _TB_START:
            self.lines.append(line)
            self.done = False
            return True
        return False

    def entry(self) -> Entry:
        exc = next(
            (
                ln
                for ln in reversed(self.lines)
                if ln and not ln[0].isspace() and ln not in _TB_CHAIN and ln != _TB_START
            ),
            "",
        )
        return Entry(
            ts=self.ts,
            source="journal",
            line=self.index,
            kind="traceback",
            level="ERROR",
            process=self.unit or "",
            logger="",
            message="\n".join(self.lines).rstrip(),
            unit=self.unit,
            pid=self.pid,
            fields={"exception": exc.split(":", 1)[0], "exception_line": exc},
        )


def parse_journal(lines: Iterable[str], units_prefix: str = "sstcam") -> Iterator[Entry]:
    """Entries for units whose name starts with ``units_prefix`` (the camera's).

    Service output is grouped per process: a pipe-format line opens a log entry and the raw
    lines after it (its continuation lines, which journald stores as separate records) are
    appended to it; a 'Traceback' line opens a traceback. Entries are emitted when the next
    record of the same process starts, so the output is ordered per process, not globally.
    """
    pending: dict[object, Entry] = {}  # open log entry per process (waiting for continuations)
    open_tb: dict[object, _Traceback] = {}

    def flush(key: object) -> Iterator[Entry]:
        if key in pending:
            yield pending.pop(key)
        if key in open_tb:
            yield open_tb.pop(key).entry()

    for index, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        rec = json.loads(raw)
        msg = _text(rec.get("MESSAGE"))
        manager_unit = rec.get("USER_UNIT") or rec.get("UNIT")
        service_unit = rec.get("_SYSTEMD_USER_UNIT") or rec.get("_SYSTEMD_UNIT")

        if rec.get("SYSLOG_IDENTIFIER") == "systemd" and manager_unit:
            if not str(manager_unit).startswith(units_prefix):
                continue
            ev = _unit_event(msg)
            fields: dict[str, Any] = {"event": ev[0], **ev[1]} if ev else {"event": "other"}
            for k in ("EXIT_CODE", "EXIT_STATUS", "N_RESTARTS", "JOB_RESULT"):
                if k in rec:
                    fields[k.lower()] = rec[k]
            level = _PRIORITY.get(int(rec.get("PRIORITY", 6)), "INFO")
            yield Entry(
                ts=_ts(rec),
                source="journal",
                line=index,
                kind="unit",
                level=level,
                process=str(manager_unit),
                logger="systemd",
                message=msg,
                unit=str(manager_unit),
                fields=fields,
            )
            continue

        if not (service_unit and str(service_unit).startswith(units_prefix)):
            continue
        unit = str(service_unit)
        pid = int(rec["_PID"]) if "_PID" in rec else None
        key: object = pid if pid is not None else unit

        tb = open_tb.get(key)
        if tb is not None and tb.feed(msg):
            continue

        m = PIPE.match(msg)
        if m:
            yield from flush(key)
            pending[key] = Entry(
                ts=_ts(rec),
                source="journal",
                line=index,
                kind="log",
                level=m["level"],
                process=m["process"],
                logger=f"{m['package']}.{m['context']}",
                message=m["message"],
                unit=unit,
                pid=pid,
                fields={"mirror": True},
            )
        elif msg == _TB_START:
            yield from flush(key)
            open_tb[key] = _Traceback(rec, index, unit, pid)
            open_tb[key].feed(msg)
        elif key in pending:
            e = pending[key]
            pending[key] = Entry(
                ts=e.ts,
                source=e.source,
                line=e.line,
                kind=e.kind,
                level=e.level,
                process=e.process,
                logger=e.logger,
                message=f"{e.message}\n{msg}",
                unit=e.unit,
                pid=e.pid,
                fields=e.fields,
            )
        else:
            yield from flush(key)
            yield Entry(
                ts=_ts(rec),
                source="journal",
                line=index,
                kind="stdout",
                level="INFO",
                process=unit,
                logger="",
                message=msg,
                unit=unit,
                pid=pid,
            )

    for key in list({*pending, *open_tb}):
        yield from flush(key)
