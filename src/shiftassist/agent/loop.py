"""The one agent loop (ADR-0003): model <-> read-only tools until a structured, cited answer.

The loop is deliberately small. Everything that can be code is code: tools compute features,
the runbook is retrieved deterministically, and the answer is validated without a model.
"""

import copy
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from shiftassist.agent.answer import SUBMIT_DESCRIPTION, SUBMIT_NAME, Answer, submit_schema
from shiftassist.agent.providers import Msg, Provider, ToolSpec, Turn
from shiftassist.agent.validator import Validation, validate
from shiftassist.tools import REGISTRY, Snapshot
from shiftassist.tools.runbook import Runbook

RUNBOOK_TOOLS = {"search_runbook", "get_runbook_entry"}

SYSTEM = """You are a read-only shift assistant for a telescope camera server. You help the \
operator understand what happened, using only the tools. You cannot change anything; any action \
is advice to a human.

How to work:
1. Look at the timeline for the time in question; drill into the relevant events.
2. Separate cause from consequence: one problem often produces several events.
3. Check what the evidence can tell apart (unit history, logs, monitoring features).
4. {runbook_step}
5. Finish by calling submit_answer exactly once.

Rules:
- Every factual statement is a claim with citations to IDs the tools returned. Never cite an ID \
you have not seen in a tool result. Put numbers you state into the claim's values.
- If the snapshot cannot answer, say so (status insufficient_data) instead of guessing.
- Times are UTC.
"""

RUNBOOK_STEP = (
    "Find the runbook entry that applies (get_event lists matching entries; check any "
    "`applies_if` condition; read it with get_runbook_entry). Recommend its checks and actions, "
    "and say when an entry is a draft. If no entry covers the situation, use status "
    "not_in_runbook and recommend escalation to the camera expert. Never invent a procedure."
)
NO_RUNBOOK_STEP = (
    "There is no runbook in this configuration. Recommend checks only where the evidence "
    "supports them; say plainly when a situation needs an expert."
)


@dataclass
class Step:
    n: int
    text: str
    calls: list[dict[str, Any]]
    usage: dict[str, int]
    seconds: float


@dataclass
class RunResult:
    question: str
    provider: str
    model: str
    use_runbook: bool
    stop: str  # submitted | max_steps | no_answer
    answer: Answer | None
    validation: Validation | None
    steps: list[Step] = field(default_factory=list)
    schema_errors: int = 0
    tool_errors: int = 0

    @property
    def usage(self) -> dict[str, int]:
        tot: dict[str, int] = {}
        for s in self.steps:
            for k, v in s.usage.items():
                tot[k] = tot.get(k, 0) + v
        return tot

    def to_json(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "provider": self.provider,
            "model": self.model,
            "use_runbook": self.use_runbook,
            "stop": self.stop,
            "answer": self.answer.model_dump() if self.answer else None,
            "validation": self.validation.summary() if self.validation else None,
            "schema_errors": self.schema_errors,
            "tool_errors": self.tool_errors,
            "usage": self.usage,
            "steps": [s.__dict__ for s in self.steps],
        }


def tool_specs(use_runbook: bool) -> list[ToolSpec]:
    specs = [
        ToolSpec(t.name, t.description, t.input_schema())
        for t in REGISTRY.values()
        if use_runbook or t.name not in RUNBOOK_TOOLS
    ]
    return [*specs, ToolSpec(SUBMIT_NAME, SUBMIT_DESCRIPTION, submit_schema())]


def run(
    question: str,
    snap: Snapshot,
    provider: Provider,
    window: tuple[datetime, datetime] | None = None,
    use_runbook: bool = True,
    max_steps: int = 12,
) -> RunResult:
    if not use_runbook:  # ablation: the same tools and data, no runbook anywhere
        snap = copy.copy(snap)
        snap.runbook = Runbook([])
    system = SYSTEM.format(runbook_step=RUNBOOK_STEP if use_runbook else NO_RUNBOOK_STEP)
    specs = tool_specs(use_runbook)
    allowed = {s.name for s in specs}
    context = (
        f"Camera snapshot {snap.camera}, data from {snap.start:%Y-%m-%dT%H:%M:%SZ} "
        f"to {snap.end:%Y-%m-%dT%H:%M:%SZ}."
    )
    if window:
        a, b = (f"{t:%Y-%m-%dT%H:%M:%SZ}" for t in window)
        context += f" The question is about {a} to {b}."
    messages: list[Msg] = [{"role": "user", "text": f"{context}\n\n{question}"}]
    res = RunResult(question, provider.name, provider.model, use_runbook, "max_steps", None, None)
    nudged = False
    for n in range(max_steps):
        t0 = time.monotonic()
        turn: Turn = provider.complete(system, messages, specs)
        messages.append({"role": "assistant", "turn": turn})
        step = Step(n, turn.text, [], turn.usage, 0.0)
        res.steps.append(step)
        if not turn.calls:
            if nudged:
                res.stop = "no_answer"
                break
            nudged = True
            messages.append({"role": "user", "text": f"Finish by calling {SUBMIT_NAME}."})
            continue
        results: list[tuple[str, str]] = []
        for c in turn.calls:
            if c.name == SUBMIT_NAME:
                try:
                    ans = Answer.model_validate(c.args)
                except ValidationError as e:
                    res.schema_errors += 1
                    out = json.dumps(
                        {
                            "error": "answer does not match the schema",
                            "details": e.errors(include_url=False)[:5],
                        },
                        default=str,
                    )
                    step.calls.append(
                        {"tool": c.name, "args": c.args, "chars": len(out), "error": True}
                    )
                    results.append((c.id, out))
                    continue
                step.calls.append({"tool": c.name, "args": c.args, "chars": 0})
                step.seconds = time.monotonic() - t0
                res.answer, res.stop = ans, "submitted"
                res.validation = validate(ans, snap, window)
                return res
            if c.name not in allowed:
                out = json.dumps({"error": f"unknown tool {c.name!r}"})
                res.tool_errors += 1
            else:
                out = REGISTRY[c.name].call(snap, c.args)
                res.tool_errors += out.startswith('{"error"')
            step.calls.append({"tool": c.name, "args": c.args, "chars": len(out)})
            results.append((c.id, out))
        messages.append({"role": "tool", "results": results})
        step.seconds = time.monotonic() - t0
    return res
