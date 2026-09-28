"""shiftassist-collect summarise CAPTURE_DIR [--out report.md]"""

import argparse
from pathlib import Path

from shiftassist.collect.summary import render, summarise


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="shiftassist-collect", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("summarise", help="markdown summary of a camera capture")
    s.add_argument("capture")
    s.add_argument("--out", help="write the report here (default: <capture>/SUMMARY.md)")
    s.add_argument("--top", type=int, default=25)
    a = p.parse_args(argv)
    md = render(summarise(a.capture), top=a.top)
    out = Path(a.out) if a.out else Path(a.capture) / "SUMMARY.md"
    out.write_text(md)
    print(f"wrote {out} ({len(md.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
