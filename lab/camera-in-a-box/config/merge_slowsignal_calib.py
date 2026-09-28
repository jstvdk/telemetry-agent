"""Workaround for a mid-refactor branch: rebuild the single slow-signal calibration table.

On the staged branch the per-pixel table was split into ssig_calib_*/slot_<N>_coefficients.csv
(64 rows, no `pixel` column), but the slow-signal loader and the server config still expect one
CSV with columns pixel,dadov,dbdov,dcdov,a,b,c and 32*64 rows. Without it the slow-signal server
crash-loops (and pointing, which Requires= it, restarts with it).

Merges the newest ssig_calib_* directory in slot order, with pixel = slot*64 + row. Does nothing
if the single file already exists. Usage: merge_slowsignal_calib.py <data/slowsignal dir>
"""

import sys
from pathlib import Path

N_TM, N_TM_PIX = 32, 64
TARGET = "slowsig_calibration_coefficients_per_pixel_matched.csv"


def main(root: str) -> None:
    base = Path(root)
    out = base / TARGET
    if out.exists():
        print(f"{out.name} present, nothing to do")
        return
    calib = sorted(base.glob("ssig_calib_*"))[-1]
    rows = ["pixel,dadov,dbdov,dcdov,a,b,c"]
    for slot in range(N_TM):
        lines = [
            ln for ln in (calib / f"slot_{slot}_coefficients.csv").read_text().splitlines()
            if ln.strip() and not ln.startswith("#")
        ]
        if len(lines) != N_TM_PIX:
            raise SystemExit(f"slot {slot}: expected {N_TM_PIX} rows, got {len(lines)}")
        rows += [f"{slot * N_TM_PIX + i},{ln}" for i, ln in enumerate(lines)]
    out.write_text("\n".join(rows) + "\n")
    print(f"{out.name}: merged {N_TM} slots from {calib.name} ({len(rows) - 1} rows)")


if __name__ == "__main__":
    main(sys.argv[1])
