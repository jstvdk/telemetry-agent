"""ZMQ wire format: two frames, [topic, payload], both UTF-8.

    log  topic 'log.<camera>.<subsystem>'  payload '<ts> <LEVEL> <camera> <subsystem>: <text>'
    tm   topic 'tm.<camera>.<channel>'     payload JSON {"ts", "camera", "channel", "value"}

Logs are text lines, as a real process would write them, so the collector has to parse
them. Multi-line text (tracebacks) stays in one message. The v0 baseline collector reads
the same frames (topic + joined payload), so it can ingest simulated scenarios unchanged.
"""

import json
import re
from typing import Any

_LOG = re.compile(
    r"^(?P<ts>\S+) (?P<level>[A-Z]+) +(?P<camera>\S+) (?P<subsystem>[^:\s]+): (?P<text>.*)$",
    re.DOTALL,
)


def encode(rec: dict[str, Any]) -> list[bytes]:
    if rec["type"] == "log":
        topic = f"log.{rec['camera']}.{rec['subsystem']}"
        payload = f"{rec['ts']} {rec['level']:<8} {rec['camera']} {rec['subsystem']}: {rec['text']}"
    elif rec["type"] == "tm":
        topic = f"tm.{rec['camera']}.{rec['channel']}"
        payload = json.dumps(
            {
                "ts": rec["ts"],
                "camera": rec["camera"],
                "channel": rec["channel"],
                "value": rec["value"],
            }
        )
    else:
        raise ValueError(f"unknown record type {rec.get('type')!r}")
    return [topic.encode(), payload.encode()]


def decode(frames: list[bytes]) -> dict[str, Any]:
    """Inverse of encode(). Raises ValueError on anything it cannot parse."""
    if len(frames) != 2:
        raise ValueError(f"expected 2 frames, got {len(frames)}")
    topic = frames[0].decode("utf-8", errors="replace")
    payload = frames[1].decode("utf-8", errors="replace")
    if topic.startswith("tm."):
        d = json.loads(payload)
        return {
            "type": "tm",
            "ts": d["ts"],
            "camera": d["camera"],
            "channel": d["channel"],
            "value": d["value"],
        }
    if topic.startswith("log."):
        m = _LOG.match(payload)
        if not m:
            raise ValueError(f"unparseable log line: {payload[:80]!r}")
        return {"type": "log", **m.groupdict()}
    raise ValueError(f"unknown topic {topic!r}")
