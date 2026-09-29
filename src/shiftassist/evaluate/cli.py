"""shiftassist-eval-agent CAPTURE --map MAP [--provider baseline|anthropic|openai] [-k N]

Runs the agent on questions generated from the capture's labels and writes a report.
"""

import argparse
import json
from collections.abc import Callable
from pathlib import Path

from shiftassist.agent.providers import AnthropicProvider, OpenAICompatProvider, Provider
from shiftassist.collect.evidence import Capture
from shiftassist.evaluate.agent import evaluate, load_map
from shiftassist.evaluate.baseline import BaselineProvider
from shiftassist.tools import Snapshot


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="shiftassist-eval-agent", description=__doc__)
    p.add_argument("capture")
    p.add_argument("--map", required=True, help="fault kind -> runbook entry (YAML)")
    p.add_argument("--profile")
    p.add_argument("--provider", choices=["baseline", "anthropic", "openai"], default="baseline")
    p.add_argument("--model")
    p.add_argument("--base-url", default="http://localhost:11434/v1")
    p.add_argument("--no-runbook", action="store_true")
    p.add_argument("-k", type=int, default=1, help="repeats per question (pass^k)")
    p.add_argument("-o", "--out", required=True, help="report directory")
    a = p.parse_args(argv)

    make: Callable[[], Provider]
    if a.provider == "baseline":
        make = BaselineProvider
    elif a.provider == "anthropic":
        make = lambda: AnthropicProvider(model=a.model or "claude-sonnet-5")  # noqa: E731
    else:
        make = lambda: OpenAICompatProvider(model=a.model, base_url=a.base_url)  # noqa: E731
    snap = Snapshot(a.capture, profile=a.profile)
    labels = Capture(a.capture).labels()
    out = Path(a.out)
    rep = evaluate(snap, labels, load_map(a.map), make, not a.no_runbook, a.k, out / "runs")
    out.mkdir(parents=True, exist_ok=True)
    summary = rep.summary() | {"config": rep.config, "capture": rep.capture}
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    (out / "rows.jsonl").write_text("".join(json.dumps(r, default=str) + "\n" for r in rep.rows))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
