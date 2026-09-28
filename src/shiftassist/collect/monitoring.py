"""Flatten decoded gatherer monitoring (one JSON object per message) into telemetry samples.

Numbers, booleans and protobuf int64-as-string fields become samples; nested messages become
dotted channel names; numeric lists get an index. Encoded n-d arrays ({dtype, shape, data}) and
timestamps are skipped. Slow-signal messages are per TARGET module: the module slot becomes the
sample's ``entity`` ('tm07'), so channels are comparable across modules.
"""

import json
from collections.abc import Iterable, Iterator
from datetime import datetime
from typing import Any

from shiftassist.collect.model import Sample

_SKIP = {"subsystem", "timestamp", "timestamp_primary", "timestamp_aux", "tm_slot", "tm_index"}


def _numeric(v: Any) -> float | None:
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, int | float):
        return float(v)
    if isinstance(v, str):
        try:
            return float(int(v))  # protobuf JSON encodes int64 as string
        except ValueError:
            return None
    return None


def _flatten(prefix: str, v: Any) -> Iterator[tuple[str, float]]:
    if isinstance(v, dict):
        if {"dtype", "shape", "data"} <= v.keys():  # encoded array: not a scalar channel
            return
        for k, x in v.items():
            yield from _flatten(f"{prefix}.{k}" if prefix else k, x)
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from _flatten(f"{prefix}.{i}", x)
    else:
        num = _numeric(v)
        if num is not None:
            yield prefix, num


def iter_samples(lines: Iterable[str]) -> Iterator[Sample]:
    for raw in lines:
        if not raw.strip():
            continue
        msg = json.loads(raw)
        ts = datetime.fromisoformat(msg["timestamp"].replace("Z", "+00:00"))
        subsystem = msg["subsystem"]
        entity = f"tm{int(msg['tm_slot']):02d}" if "tm_slot" in msg else ""
        body = {k: v for k, v in msg.items() if k not in _SKIP}
        for channel, value in _flatten("", body):
            yield Sample(ts, subsystem, entity, channel, value)
