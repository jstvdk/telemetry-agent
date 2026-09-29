#!/usr/bin/env bash
# Rebuild a capture from a camera container that stopped mid-run (Docker quit, host reboot),
# without booting the camera again: copy /data and the journal out of the stopped container and
# decode them in throwaway containers, exactly as capture.sh would have (P-24).
#   salvage.sh <capture-name> [container]
# run.json is not written: the harness never finished. Write it by hand with the covered window
# (from the harness start to the first shutdown record) and "reconstructed": true.
set -euo pipefail
NAME=${1:?usage: salvage.sh <capture-name> [container]}
C=${2:-cam-01}
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$HERE/captures/$NAME
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
IMAGE=$(docker inspect "$C" --format '{{.Config.Image}}')
[ "$(docker inspect "$C" --format '{{.State.Running}}')" = false ] || { echo "$C is running: use capture.sh" >&2; exit 1; }
mkdir -p "$OUT"
docker cp "$C:/data/SSTCAM" "$TMP/SSTCAM"
docker cp "$C:/var/log/journal" "$TMP/journal"
docker run --rm --entrypoint /opt/sstcam/venv/bin/python -v "$TMP/SSTCAM/monitoring:/in:ro" \
  -v "$HERE/lab/export_monitoring.py:/x/e.py:ro" "$IMAGE" /x/e.py /in \
  > "$OUT/monitoring.jsonl" 2> "$OUT/export.log"
docker run --rm --entrypoint journalctl -v "$TMP/journal:/j:ro" "$IMAGE" \
  --directory="/j/$(ls "$TMP/journal" | head -1)" -o json --no-pager > "$OUT/journal.jsonl"
rm -rf "$OUT/data" && cp -R "$TMP/SSTCAM" "$OUT/data"
cat "$OUT/export.log" >&2
echo "salvaged $C -> $OUT (write run.json by hand, see header)" >&2
