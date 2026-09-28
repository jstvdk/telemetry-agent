"""Simulated time: offsets are integer milliseconds from scenario start; output is ISO-8601 UTC."""

import re
from datetime import UTC, datetime, timedelta

_DURATION = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?$")


def parse_duration_ms(text: str) -> int:
    """Parse '3h50m', '23m', '40s', '1h', '0s' into milliseconds."""
    m = _DURATION.fullmatch(text.strip())
    if not m or not any(m.groups()):
        raise ValueError(f"invalid duration {text!r}; expected e.g. '3h50m', '40s'")
    h, mins, s = m.groups()
    return int(h or 0) * 3_600_000 + int(mins or 0) * 60_000 + round(float(s or 0) * 1000)


def iso(start: datetime, offset_ms: int) -> str:
    """ISO-8601 UTC with millisecond precision and a 'Z' suffix."""
    t = (start + timedelta(milliseconds=offset_ms)).astimezone(UTC)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def parse_iso(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))
