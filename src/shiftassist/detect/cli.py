"""shiftassist-detect profile BASELINE... -o PROFILE | run CAPTURE -p PROFILE | score CAPTURE"""

import argparse
import json
from pathlib import Path

from shiftassist.collect.evidence import Capture
from shiftassist.detect.model import Event
from shiftassist.detect.profile import Profile, learn
from shiftassist.detect.rules import detect
from shiftassist.detect.score import render, score
from shiftassist.sim.timeutil import parse_iso


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="shiftassist-detect", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    a_prof = sub.add_parser("profile", help="learn normal behaviour from clean captures")
    a_prof.add_argument("capture", nargs="+")
    a_prof.add_argument("-o", "--out", required=True)
    a_run = sub.add_parser("run", help="detect events in a capture (labels are not read)")
    a_run.add_argument("capture")
    a_run.add_argument("-p", "--profile", required=True)
    a_sc = sub.add_parser("score", help="score <capture>/events.jsonl against its labels")
    a_sc.add_argument("capture")
    a_sc.add_argument(
        "--run-window",
        action="store_true",
        help="score only events inside the harness run (run.json); for captures that also "
        "contain an earlier run on the same camera",
    )
    a_sc.add_argument(
        "--only-validated",
        action="store_true",
        help="drop expected events whose evidence is absent (collect verify-labels)",
    )
    a = p.parse_args(argv)

    if a.cmd == "profile":
        prof = learn(list(a.capture))
        prof.save(a.out)
        print(
            f"profile from {prof.learned_from}: {len(prof.sources)} sources, "
            f"{len(prof.trend)} trend families, {len(prof.known_templates)} known templates "
            f"-> {a.out}"
        )
        return 0

    cap = Path(a.capture)
    if a.cmd == "run":
        events = detect(str(cap), Profile.load(a.profile))
        (cap / "events.jsonl").write_text("".join(e.model_dump_json() + "\n" for e in events))
        lines = ["| id | time | kind | severity | source | summary |", "|---|---|---|---|---|---|"]
        lines += [
            f"| {e.event_id} | {e.ts:%H:%M:%S} | {e.kind} | {e.severity} | {e.subsystem}"
            f"{'/' + e.entity if e.entity else ''} | {e.summary} |"
            for e in events
        ]
        (cap / "EVENTS.md").write_text("\n".join(lines) + "\n")
        print(f"{len(events)} events -> {cap / 'events.jsonl'}")
        return 0

    events = [
        Event.model_validate_json(x)
        for x in (cap / "events.jsonl").read_text().splitlines()
        if x.strip()
    ]
    c = Capture(cap)
    labels = c.labels() if (cap / "labels.jsonl").exists() else []
    if a.only_validated and labels:
        from shiftassist.collect.evidence import verify

        bad = {(ch.label_id, ch.event.model_dump_json()) for ch in verify(cap) if ch.found is False}
        labels = [
            lb.model_copy(
                update={
                    "expected_events": [
                        e
                        for e in lb.expected_events
                        if (lb.label_id, e.model_dump_json()) not in bad
                    ]
                }
            )
            for lb in labels
        ]
        print(f"excluded {len(bad)} expected event(s) without evidence in the data")
    first, last = c.span
    if a.run_window:
        run = json.loads((cap / "run.json").read_text())
        first, last = parse_iso(run["start"]), parse_iso(run["end"])
        events = [e for e in events if first <= e.ts <= last]
        print(f"run window {run['start']} .. {run['end']}: {len(events)} events")
    s = score(cap.name, events, labels, (last - first).total_seconds() / 3600)
    md = render(s)
    (cap / "SCORE.md").write_text(md)
    print("\n".join(md.splitlines()[:14]))
    (cap / "score.json").write_text(
        json.dumps(
            {
                "recall": s.recall,
                "recall_exact": s.recall_exact,
                "events": s.n_events,
                "precision_strict": s.precision_strict,
                "precision_lenient": s.precision_lenient,
                "duplicates": len(s.duplicates),
                "false_alarms": len(s.false_alarms),
                "false_alarms_per_hour": s.false_alarms_per_hour,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
