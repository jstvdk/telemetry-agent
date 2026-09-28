"""shiftassist-sim run SCENARIO.yaml --out DIR | shiftassist-sim publish STREAM.jsonl"""

import argparse
import sys

from shiftassist.sim.generator import generate, write
from shiftassist.sim.publish import publish, read_stream
from shiftassist.sim.scenario import load_scenario


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="shiftassist-sim", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="generate stream + ground-truth labels for a scenario")
    r.add_argument("scenario")
    r.add_argument("--out", required=True, help="output directory")
    r.add_argument("--seed", type=int, help="override the scenario seed")

    pb = sub.add_parser("publish", help="replay a stream.jsonl on a ZMQ PUB socket")
    pb.add_argument("stream")
    pb.add_argument("--address", default="tcp://*:5556")
    pb.add_argument("--speed", type=float, default=60.0, help="x real time; 0 = no delay")
    pb.add_argument("--warmup", type=float, default=1.0, help="seconds to wait for subscribers")

    a = p.parse_args(argv)
    if a.cmd == "run":
        result = generate(load_scenario(a.scenario), seed=a.seed)
        m = write(result, a.out)
        c = m["counts"]
        print(
            f"{result.scenario.id} seed={result.seed}: {c['logs']} log lines, "
            f"{c['telemetry']} telemetry samples, {c['labels']} labels -> {a.out}"
        )
    else:
        n = publish(read_stream(a.stream), a.address, a.speed, a.warmup, verbose=True)
        print(f"published {n} messages", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
