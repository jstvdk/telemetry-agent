"""Replay a generated stream on a ZMQ PUB socket, optionally time-accelerated."""

import json
import sys
import time
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import zmq

from shiftassist.sim.timeutil import parse_iso
from shiftassist.sim.wire import encode


def read_stream(path: str | Path) -> Iterator[dict[str, Any]]:
    with open(path) as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def publish(
    records: Iterable[dict[str, Any]],
    address: str,
    speed: float = 60.0,
    warmup_s: float = 1.0,
    context: zmq.Context[zmq.Socket[bytes]] | None = None,
    verbose: bool = False,
) -> int:
    """Send records in timestamp order. speed=60 plays one simulated minute per second;
    speed<=0 sends as fast as possible. Returns the number of messages sent."""
    ctx = context or zmq.Context.instance()
    sock = ctx.socket(zmq.PUB)
    sock.setsockopt(zmq.SNDHWM, 0)  # never drop on a slow subscriber during replay
    sock.bind(address)
    time.sleep(warmup_s)  # PUB/SUB "slow joiner": give subscribers time to connect

    n = 0
    t_first: float | None = None
    wall_start = time.monotonic()
    try:
        for rec in records:
            t = parse_iso(rec["ts"]).timestamp()
            t_first = t if t_first is None else t_first
            if speed > 0:
                delay = (t - t_first) / speed - (time.monotonic() - wall_start)
                if delay > 0:
                    time.sleep(delay)
            sock.send_multipart(encode(rec))
            n += 1
            if verbose and n % 1000 == 0:
                print(f"{n} messages sent (sim time {rec['ts']})", file=sys.stderr)
    finally:
        sock.close(linger=2000)
    return n
