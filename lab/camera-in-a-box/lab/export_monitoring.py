"""Decode the gatherer's binary monitoring files to JSON lines.

    python export_monitoring.py /data/SSTCAM/monitoring > monitoring.jsonl

One line per GatheredMonitoringMessage:
    {"subsystem": <oneof name>, "gathered_at": <gatherer receive time>, ...fields as protobuf JSON}
`timestamp` inside the fields is the source's own time; `gathered_at` is when the gatherer took
the message off the socket (it stamps datetime.now() in its handler). A frozen gatherer loses
nothing but writes late, so the difference is what shows a hang (R20).

Files are found with the project's own handler (DailyRotatingBinaryFileHandler.file_paths) and use
its record format (4-byte little-endian length + serialized message). Unlike the project's reader,
this one does not give up at a damaged record: a short write (e.g. on a full disk, R21) leaves a
partial record, after which every length is read at the wrong offset and the project's reader
skips the rest of the file. Here the reader resynchronises at the next offset where RESYNC_CHAIN
records in a row parse, and reports every skipped byte range on stderr and in --damage FILE.
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

from google.protobuf.json_format import MessageToDict
from google.protobuf.message import DecodeError
from sstcam_telecom.protobuf.gatherer.v1alpha1.telemetry_pb2 import GatheredMonitoringMessage
from sstcam_telecom.protobuf.io import DailyRotatingBinaryFileHandler

MAX_LEN = 100_000_000  # the project's own sanity bound
RESYNC_CHAIN = 20  # records in a row that must parse before we trust a resync point


def _parse(buf: bytes, off: int) -> tuple[GatheredMonitoringMessage, int] | None:
    if off + 4 > len(buf):
        return None
    n = int.from_bytes(buf[off : off + 4], "little")
    if n <= 0 or n > MAX_LEN or off + 4 + n > len(buf):
        return None
    msg = GatheredMonitoringMessage()
    try:
        msg.ParseFromString(buf[off + 4 : off + 4 + n])
    except DecodeError:
        return None
    if msg.WhichOneof("monitoring_message") is None or not msg.HasField("timestamp"):
        return None
    return msg, off + 4 + n


def _chain_ok(buf: bytes, off: int) -> bool:
    for _ in range(RESYNC_CHAIN):
        r = _parse(buf, off)
        if r is None:
            return off == len(buf)  # a clean end of file also counts
        off = r[1]
    return True


def read_file(path: Path, damage: list[dict]):
    buf = path.read_bytes()
    off = 0
    while off < len(buf):
        r = _parse(buf, off)
        if r is not None:
            yield r[0]
            off = r[1]
            continue
        start = off
        off += 1
        while off < len(buf) and not _chain_ok(buf, off):
            off += 1
        damage.append({"file": path.name, "offset": start, "skipped_bytes": off - start,
                       "resumed": off < len(buf)})  # fmt: skip
        print(f"damaged record in {path.name} at {start}: skipped {off - start} bytes",
              file=sys.stderr)  # fmt: skip


def export(directory: str, damage: list[dict], prefix: str = "monitoring") -> int:
    days = sorted({date.fromisoformat(m.group(1)) for p in Path(directory).glob(f"{prefix}_*.bin")
                   if (m := re.match(rf"{prefix}_(\d{{4}}-\d{{2}}-\d{{2}})", p.name))})
    handler = DailyRotatingBinaryFileHandler.for_reading(directory=directory, prefix=prefix)
    n = 0
    for day in days:
        for path in [*handler._legacy_file_paths(day), *handler.file_paths(day)]:
            for msg in read_file(Path(path), damage):
                kind = msg.WhichOneof("monitoring_message")
                body = MessageToDict(
                    getattr(msg, kind),
                    preserving_proto_field_name=True,
                    always_print_fields_with_no_presence=True,  # else zeros (e.g. slot 0) vanish
                )
                gathered = msg.timestamp.ToDatetime().isoformat(timespec="milliseconds") + "Z"
                sys.stdout.write(json.dumps({"subsystem": kind, "gathered_at": gathered, **body}) + "\n")
                n += 1
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("directory")
    ap.add_argument("--damage", help="write skipped byte ranges as JSON")
    a = ap.parse_args()
    damage: list[dict] = []
    n = export(a.directory, damage)
    if a.damage:
        Path(a.damage).write_text(json.dumps(damage, indent=2) + "\n")
    print(f"exported {n} messages; {len(damage)} damaged range(s)", file=sys.stderr)
