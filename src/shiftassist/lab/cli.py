"""shiftassist-lab run SCENARIO.yaml | reset | check   (see lab/camera-in-a-box/README.md)"""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from shiftassist.lab.box import Box, open_log
from shiftassist.lab.faults import reset_to_nominal
from shiftassist.lab.harness import check_healthy, load_scenario, run

LAB = Path(__file__).resolve().parents[3] / "lab" / "camera-in-a-box"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="shiftassist-lab", description=__doc__)
    p.add_argument("--container", default="cam-01")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a scenario, then capture the camera's output")
    r.add_argument("scenario")
    r.add_argument("--dry-run", action="store_true", help="log the commands, touch nothing")
    r.add_argument("--no-capture", action="store_true")
    sub.add_parser("reset", help="undo every catalog fault; bring all units back")
    sub.add_parser("check", help="report whether the camera is healthy")
    a = p.parse_args(argv)

    if a.cmd == "check":
        problems = check_healthy(Box(a.container))
        print("healthy" if not problems else "\n".join(problems))
        return 0 if not problems else 1
    if a.cmd == "reset":
        reset_to_nominal(Box(a.container))
        print("reset done")
        return 0

    sc = load_scenario(a.scenario)
    name = f"{sc.id}-{datetime.now():%Y%m%dT%H%M%S}" + ("-dry" if a.dry_run else "")
    out = LAB / "captures" / name
    with open_log(out / "harness.jsonl") as log:
        box = Box(a.container, dry_run=a.dry_run, log_file=log)
        result = run(sc, box, out)
    print(
        f"{sc.id}: {len(result.labels)} faults labelled"
        + (f", ABORTED: {result.aborted}" if result.aborted else "")
        + f" -> {out}"
    )
    if not a.dry_run and not a.no_capture:
        subprocess.run([str(LAB / "capture.sh"), name, a.container], check=True)
    return 1 if result.aborted else 0


if __name__ == "__main__":
    sys.exit(main())
