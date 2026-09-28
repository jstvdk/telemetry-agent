import socket
import threading
from typing import Any

import pytest
import zmq

from shiftassist.sim.generator import generate, record_to_dict
from shiftassist.sim.publish import publish
from shiftassist.sim.wire import decode, encode
from tests.conftest import scenario

LOG = {
    "type": "log",
    "ts": "2026-10-15T02:13:00.000Z",
    "camera": "cam-01",
    "subsystem": "readout",
    "level": "ERROR",
    "text": 'Unhandled exception\nTraceback (most recent call last):\n  File "x.py"\nBoom: no',
}
TM = {
    "type": "tm",
    "ts": "2026-10-15T02:13:00.000Z",
    "camera": "cam-01",
    "channel": "cooling.plate_temp_c",
    "value": 15.123,
}


@pytest.mark.parametrize("rec", [LOG, TM], ids=["log-multiline", "telemetry"])
def test_roundtrip(rec: dict[str, Any]) -> None:
    assert decode(encode(rec)) == rec


def test_topic_prefix_allows_subscription_filtering() -> None:
    assert encode(LOG)[0] == b"log.cam-01.readout"
    assert encode(TM)[0] == b"tm.cam-01.cooling.plate_temp_c"


def test_v0_collector_view_contains_level() -> None:
    """v0 stores ' '.join(payload frames) as text; the level word is part of it."""
    _, payload = encode(LOG)
    assert payload.decode().split()[1] == "ERROR"


@pytest.mark.parametrize("frames", [[b"x"], [b"log.a.b", b"not a log line"], [b"zz", b"{}"]])
def test_decode_rejects_garbage(frames: list[bytes]) -> None:
    with pytest.raises(ValueError):
        decode(frames)


def test_whole_scenario_roundtrips() -> None:
    r = generate(scenario("S03"))
    for rec in r.records:
        d = record_to_dict(rec, r.scenario)
        assert decode(encode(d)) == d


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.mark.zmq
def test_publish_delivers_everything_in_order() -> None:
    r = generate(scenario("S07"))
    recs = [record_to_dict(x, r.scenario) for x in r.records[:500]]
    addr = f"tcp://127.0.0.1:{_free_port()}"

    ctx: zmq.Context[zmq.Socket[bytes]] = zmq.Context()
    sub = ctx.socket(zmq.SUB)
    sub.setsockopt(zmq.SUBSCRIBE, b"")
    sub.setsockopt(zmq.RCVTIMEO, 5000)
    sub.connect(addr)  # connect before bind is fine for tcp; zmq retries

    t = threading.Thread(
        target=publish, args=(recs, addr), kwargs={"speed": 0, "warmup_s": 0.5, "context": ctx}
    )
    t.start()
    got = [decode(sub.recv_multipart()) for _ in recs]
    t.join()
    sub.close(linger=0)
    ctx.term()
    assert got == recs
