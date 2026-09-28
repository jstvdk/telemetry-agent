#!/usr/bin/env bash
# Copy everything one camera produced into lab/captures/<name>/ (git-ignored):
#   data/            /data/SSTCAM as written (per-process logs, central log, config snapshot, .bin)
#   journal.jsonl    system + user journal, JSON export (restarts, exits, stdout of services)
#   monitoring.jsonl gatherer monitoring decoded with the project's own reader
#   units.txt        final unit states and restart counters
#   manifest.json    image labels, container, time window
set -euo pipefail
NAME=${1:?usage: capture.sh <capture-name> [container]}
C=${2:-cam-01}
OUT=$(cd "$(dirname "$0")" && pwd)/captures/$NAME
mkdir -p "$OUT"

docker exec "$C" tar -C /data -cf - SSTCAM | tar -C "$OUT" -xf - && mv "$OUT/SSTCAM" "$OUT/data"
docker exec "$C" journalctl -o json --no-pager > "$OUT/journal.jsonl"
docker exec "$C" ucam python /opt/sstcam/lab/export_monitoring.py /data/SSTCAM/monitoring \
  > "$OUT/monitoring.jsonl"
docker exec "$C" ucam systemctl --user show 'sstcam*' -p Id -p ActiveState -p SubState -p NRestarts \
  --no-pager > "$OUT/units.txt"
python3 - "$OUT" "$C" <<'PY'
import json, subprocess, sys, pathlib
out, c = pathlib.Path(sys.argv[1]), sys.argv[2]
info = json.loads(subprocess.check_output(["docker", "inspect", c]))[0]
first = last = None
with open(out / "journal.jsonl") as fh:
    for line in fh:
        ts = int(json.loads(line)["__REALTIME_TIMESTAMP"]); first = first or ts; last = ts
m = {"container": c, "image": info["Config"]["Image"], "labels": info["Config"]["Labels"],
     "started": info["State"]["StartedAt"], "journal_first_us": first, "journal_last_us": last}
(out / "manifest.json").write_text(json.dumps(m, indent=2) + "\n")
PY
du -sh "$OUT"/* | sed "s|$OUT/||"
