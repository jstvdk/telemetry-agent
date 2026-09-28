"""Parsers for the camera server's two text log formats.

pipe (per-process files, terminal/journal stdout):
    26-09-28 18:25:43 | INFO     | CHILLER-SERVER      | sstcam_configuration | SETUP  | message
central (gatherer file, ICD format):
    26-09-28T18:26:05.288 WARNING /path/x.py 215 convert_spi_temp SLOWSIGNAL-SERVER Developer msg

Both write multi-line messages as a header line followed by continuation lines that carry no
timestamp or level; those are joined back into one entry. Timestamps have a 2-digit year and
no zone (the pipe format also has only 1 s resolution); ``tz`` says which zone they are in.
"""

import re
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime, tzinfo
from pathlib import Path
from typing import Literal

from shiftassist.collect.model import LEVELS, Entry

Dialect = Literal["pipe", "central"]

_LEVEL = "|".join(LEVELS)
# The message may itself contain ' | ' (e.g. 'TM|SIPM|FPE IDs: 04: 31 | 70430021 |'), so the
# four fixed fields are matched lazily and the message takes the rest.
PIPE = re.compile(
    rf"^(?P<ts>\d{{2}}-\d{{2}}-\d{{2}} \d{{2}}:\d{{2}}:\d{{2}}) \| (?P<level>{_LEVEL}) *"
    r" \| (?P<process>.*?) *\| (?P<package>.*?) *\| (?P<context>.*?) *\| (?P<message>.*)$"
)
CENTRAL = re.compile(
    rf"^(?P<ts>\d{{2}}-\d{{2}}-\d{{2}}T\d{{2}}:\d{{2}}:\d{{2}}\.\d{{3}}) (?P<level>{_LEVEL}) "
    r"(?P<path>\S+) (?P<lineno>\d+) (?P<func>\S+) (?P<process>\S+) (?P<audience>\S+) "
    r"(?P<message>.*)$"
)
_FORMATS = {"pipe": (PIPE, "%y-%m-%d %H:%M:%S"), "central": (CENTRAL, "%y-%m-%dT%H:%M:%S.%f")}


def sniff(line: str) -> Dialect | None:
    for name, (rx, _) in _FORMATS.items():
        if rx.match(line):
            return name  # type: ignore[return-value]
    return None


def parse_line(line: str, dialect: Dialect) -> dict[str, str] | None:
    """Header fields of one line, or None if it is a continuation line."""
    rx, _ = _FORMATS[dialect]
    m = rx.match(line)
    return m.groupdict() if m else None


def parse_lines(
    lines: Iterable[str], dialect: Dialect, source: str, tz: tzinfo = UTC
) -> Iterator[Entry]:
    """Group header + continuation lines into entries. Lines before the first header (a file
    that starts mid-record) are dropped; there is nothing to attach them to."""
    rx, datefmt = _FORMATS[dialect]
    head: dict[str, str] | None = None
    head_line = 0
    extra: list[str] = []

    def emit() -> Entry:
        assert head is not None
        ts = datetime.strptime(head["ts"], datefmt).replace(tzinfo=tz).astimezone(UTC)
        message = "\n".join([head["message"], *extra])
        if dialect == "pipe":
            logger = f"{head['package']}.{head['context']}"
            fields = {}
        else:
            logger = f"{head['path']}:{head['lineno']} {head['func']}"
            fields = {"path": head["path"], "lineno": int(head["lineno"]), "func": head["func"]}
        return Entry(
            ts=ts,
            source=source,
            line=head_line,
            kind="log",
            level=head["level"],
            process=head["process"],
            logger=logger,
            message=message,
            fields=fields,
        )

    for n, raw in enumerate(lines, start=1):
        line = raw.rstrip("\n")
        m = rx.match(line)
        if m:
            if head is not None:
                yield emit()
            head, head_line, extra = m.groupdict(), n, []
        elif head is not None:
            extra.append(line)
    if head is not None:
        yield emit()


def read_log_file(path: str | Path, source: str | None = None, tz: tzinfo = UTC) -> Iterator[Entry]:
    """Parse one camera log file; the dialect is detected from its first header line."""
    p = Path(path)
    with p.open(encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()
    dialect = next((d for d in map(sniff, lines) if d), None)
    if dialect is None:
        return
    prefix = "central" if dialect == "central" else "log"
    yield from parse_lines(lines, dialect, source or f"{prefix}/{p.name}", tz)
