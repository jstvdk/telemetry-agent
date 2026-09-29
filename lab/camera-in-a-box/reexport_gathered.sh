#!/usr/bin/env bash
# Add the gatherer's receive time ("gathered_at") to an existing capture's monitoring.jsonl.
# Captures made before 2026-09-29 were exported without it (P-17). Decodes the capture's own
# .bin files in a throwaway container (no camera started), then merges the field into the
# existing records, after checking that every decoded record is identical to the one it
# annotates. Records written after the capture's file copy (the tail of the live export) keep
# no gathered_at: unknown, not zero.
set -euo pipefail
CAP=$(cd "${1:?usage: reexport_gathered.sh <capture-dir>}" && pwd)
HERE=$(cd "$(dirname "$0")" && pwd)
docker run --rm --entrypoint /opt/sstcam/venv/bin/python \
  -v "$CAP/data/monitoring:/in:ro" -v "$HERE/lab/export_monitoring.py:/x/export_monitoring.py:ro" \
  camera-in-a-box:dev /x/export_monitoring.py /in > "$CAP/.monitoring.gathered.jsonl"
python3 - "$CAP" <<'PY'
import json, sys, pathlib
cap = pathlib.Path(sys.argv[1])
src, new = cap / "monitoring.jsonl", cap / ".monitoring.gathered.jsonl"
out = cap / ".monitoring.merged.jsonl"
n = tail = 0
with src.open() as a, new.open() as b, out.open("w") as o:
    for line in a:
        r = json.loads(line)
        g = b.readline()
        if g:
            gr = json.loads(g)
            ga = gr.pop("gathered_at")
            if gr != {k: v for k, v in r.items() if k != "gathered_at"}:
                sys.exit(f"record {n} differs; not merging")
            r = {"subsystem": r["subsystem"], "gathered_at": ga, **{k: v for k, v in r.items() if k != "subsystem"}}
            n += 1
        else:
            tail += 1
        o.write(json.dumps(r) + "\n")
    if b.readline():
        sys.exit("decoded more records than the capture has; not merging")
out.replace(src)
new.unlink()
print(f"{cap.name}: gathered_at added to {n} records, {tail} tail records without it")
PY
