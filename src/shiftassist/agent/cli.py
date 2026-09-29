"""shiftassist-ask CAPTURE "question" [--provider anthropic|openai] [--model M] [--no-runbook]

Runs the agent on one snapshot and prints the validated answer. Writes the full run (answer,
validation, every tool call, token usage) as JSON with -o.
"""

import argparse
import json
from pathlib import Path

from shiftassist.agent.loop import run
from shiftassist.agent.providers import AnthropicProvider, OpenAICompatProvider, Provider
from shiftassist.agent.validator import render
from shiftassist.sim.timeutil import parse_iso
from shiftassist.tools import Snapshot


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="shiftassist-ask", description=__doc__)
    p.add_argument("capture")
    p.add_argument("question")
    p.add_argument("--profile")
    p.add_argument("--provider", choices=["anthropic", "openai"], default="anthropic")
    p.add_argument("--model", help="default: claude-sonnet-5 (anthropic); required for openai")
    p.add_argument("--base-url", default="http://localhost:11434/v1", help="openai-compatible")
    p.add_argument("--no-runbook", action="store_true")
    p.add_argument("--start", help="question window start (ISO UTC)")
    p.add_argument("--end", help="question window end (ISO UTC)")
    p.add_argument("--max-steps", type=int, default=12)
    p.add_argument("-o", "--out", help="write the full run as JSON")
    a = p.parse_args(argv)

    provider: Provider
    if a.provider == "anthropic":
        provider = AnthropicProvider(model=a.model or "claude-sonnet-5")
    else:
        if not a.model:
            p.error("--model is required for --provider openai")
        provider = OpenAICompatProvider(model=a.model, base_url=a.base_url)
    snap = Snapshot(a.capture, profile=a.profile)
    window = (parse_iso(a.start), parse_iso(a.end)) if a.start and a.end else None
    res = run(a.question, snap, provider, window, not a.no_runbook, a.max_steps)
    if res.answer and res.validation:
        print(render(res.answer, res.validation))
        print(f"\nvalidation: {res.validation.summary()}")
    else:
        print(f"no answer ({res.stop})")
    print(f"steps: {len(res.steps)}, tokens: {res.usage}")
    if a.out:
        Path(a.out).write_text(json.dumps(res.to_json(), indent=2, default=str))
    return 0 if res.stop == "submitted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
