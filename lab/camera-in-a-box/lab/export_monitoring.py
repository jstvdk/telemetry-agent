"""Decode the gatherer's binary monitoring files to JSON lines, using the project's own reader.

    python export_monitoring.py /data/SSTCAM/monitoring > monitoring.jsonl

One line per GatheredMonitoringMessage:
    {"subsystem": <oneof name>, "gathered_at": <gatherer receive time>, ...fields as protobuf JSON}
`timestamp` inside the fields is the source's own time; `gathered_at` is when the gatherer took
the message off the socket (it stamps datetime.now() in its handler). A frozen gatherer loses
nothing but writes late, so the difference is what shows a hang (R20).
Reads every observation day present in the directory.
"""

import asyncio
import json
import re
import sys
from datetime import date
from pathlib import Path

from google.protobuf.json_format import MessageToDict
from sstcam_telecom.protobuf.gatherer.v1alpha1.telemetry_pb2 import GatheredMonitoringMessage
from sstcam_telecom.protobuf.io import DailyRotatingBinaryFileHandler


async def export(directory: str, prefix: str = "monitoring") -> int:
    days = sorted({date.fromisoformat(m.group(1)) for p in Path(directory).glob(f"{prefix}_*.bin")
                   if (m := re.match(rf"{prefix}_(\d{{4}}-\d{{2}}-\d{{2}})", p.name))})
    reader = DailyRotatingBinaryFileHandler.for_reading(directory=directory, prefix=prefix)
    n = 0
    for day in days:
        async for msg in reader.read_messages(GatheredMonitoringMessage, day):
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
    n = asyncio.run(export(sys.argv[1]))
    print(f"exported {n} messages", file=sys.stderr)
