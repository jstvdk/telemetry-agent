#!/usr/bin/env bash
# Copy the camera-server sources this image is built from into .build/ (git-ignored).
# A clean copy keeps the Docker build context small and records exactly what was built.
set -euo pipefail

SSTCAM_SERVER_SRC=${SSTCAM_SERVER_SRC:-$HOME/software/ctasoft/cta-array-ellements/sst/SST-Camera/camera-server-software/sstcam-server}
CAMBRIDGE_SRC=${CAMBRIDGE_SRC:-$HOME/software/ctasoft/cta-array-ellements/common/cambridge}
OUT=${OUT:-$(dirname "$0")/.build}

EXCLUDES=(--exclude .git --exclude build/ --exclude '*.egg-info' --exclude __pycache__
          --exclude .mypy_cache --exclude .pytest_cache --exclude .ruff_cache --exclude .venv
          --exclude .DS_Store --exclude '*.pyc')

mkdir -p "$OUT"
rsync -a --delete "${EXCLUDES[@]}" "$SSTCAM_SERVER_SRC"/ "$OUT/sstcam-server/"
rsync -a --delete "${EXCLUDES[@]}" "$CAMBRIDGE_SRC"/ "$OUT/cambridge/"

describe() { git -C "$1" describe --always --dirty --tags 2>/dev/null || echo unknown; }
cat > "$OUT/SOURCES.env" <<EOT
SSTCAM_SERVER_REV=$(describe "$SSTCAM_SERVER_SRC")
SSTCAM_SERVER_BRANCH=$(git -C "$SSTCAM_SERVER_SRC" branch --show-current 2>/dev/null || echo unknown)
CAMBRIDGE_REV=$(describe "$CAMBRIDGE_SRC")
EOT
cat "$OUT/SOURCES.env"
du -sh "$OUT"/sstcam-server "$OUT"/cambridge
