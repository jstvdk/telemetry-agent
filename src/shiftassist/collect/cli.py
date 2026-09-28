"""shiftassist-collect summarise CAPTURE_DIR | verify-labels CAPTURE_DIR"""

import argparse
from pathlib import Path

from shiftassist.collect import evidence
from shiftassist.collect.summary import render, summarise


def _start(capture: Path) -> float:
    import json

    from shiftassist.sim.timeutil import parse_iso

    return parse_iso(json.loads((capture / "run.json").read_text())["start"]).timestamp()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="shiftassist-collect", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("summarise", help="markdown summary of a camera capture")
    s.add_argument("capture")
    s.add_argument("--out", help="write the report here (default: <capture>/SUMMARY.md)")
    s.add_argument("--top", type=int, default=25)
    v = sub.add_parser("verify-labels", help="check each label's expected events in the data")
    v.add_argument("capture")
    v.add_argument(
        "--labels-from",
        help="negative control: another capture's labels, moved to "
        "the same offsets from this capture's start",
    )
    a = p.parse_args(argv)
    if a.cmd == "verify-labels":
        labels = None
        if a.labels_from:
            src, dst = Path(a.labels_from), Path(a.capture)
            shift = _start(dst) - _start(src)
            labels = [evidence.shift_label(lb, shift) for lb in evidence.Capture(src).labels()]
        checks = evidence.verify(a.capture, labels)
        md = evidence.render(checks)
        name = "LABEL_CHECK.md" if labels is None else "LABEL_CHECK_negative_control.md"
        (Path(a.capture) / name).write_text(md)
        print(md)
        return 0 if all(c.found is not False for c in checks) else 1
    md = render(summarise(a.capture), top=a.top)
    out = Path(a.out) if a.out else Path(a.capture) / "SUMMARY.md"
    out.write_text(md)
    print(f"wrote {out} ({len(md.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
