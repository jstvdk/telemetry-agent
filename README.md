# Shift Assistant: a read-only LLM agent over instrument telemetry

A prototype **operator assistant** for a telescope camera. It watches logs and telemetry, detects problems with deterministic rules, and uses an LLM to **explain, correlate and write**: answering "why did the readout restart at 02:13?" with citations that code has checked, and drafting the shift log.

> **The LLM never detects and never acts.** Detection is code. Every claim cites an event or runbook section, and a validator checks it. The assistant has no write access to anything.

## Status

| Stage | State |
|---|---|
| v0 learning spike: MCP server, bare agent loop, token logging (files in the repo root) | ✅ done, [reviewed](docs/06-v0-spike-review.md) |
| v1 simulator: 10 seeded fault scenarios with ground-truth labels (`make sim SCENARIO=S03`) | ✅ M1 |
| v1 rest of the slice: detection → event timeline → tools → agent → validator → eval | 📐 designed, [plan](docs/07-delivery-plan.md) |
| Experiments: architecture vs. model, hosted vs. local models | 📐 [designed](docs/04-evaluation.md) |

## How it is designed

```
simulator ─ZMQ─▶ collector ─▶ detection ─▶ event timeline (SQLite)
 (scenarios +                (rules,          │
  ground truth)               trends)    tool registry (read-only) ──▶ MCP server
                                              │
                                agent loop ◀──┴──▶ LLM (Anthropic or local, OpenAI-compatible)
                                     │
                              grounding validator ──▶ answer / shift log
                                     │
                              eval harness (scored against scenario labels)
```

Start with the [documentation index](docs/README.md). Short path:
- **Why:** [problem and rationale](docs/01-rationale.md)
- **How it evolved:** [project journey](docs/00-journey.md), from a brainstorm to measured results
- **How:** [architecture](docs/03-architecture.md) and [decision records](docs/adr/README.md)
- **How we know it works:** [evaluation](docs/04-evaluation.md) and [test plan](docs/05-test-plan.md)

## Quickstart

Requires [uv](https://docs.astral.sh/uv/). Python 3.12 is installed by uv if missing.

```bash
make install        # .venv + package + dev tools
make test           # deterministic tests, no API key needed
```

## Repository layout

```
src/shiftassist/    v1 package (see docs/03-architecture.md §7 for the target layout)
scenarios/          simulator scenarios (YAML)
tests/
baseline/           v0 learning spike, unchanged; baseline for experiment E1
docs/               design docs, ADRs, evaluation, provenance
```

v0 needs a ZMQ publisher of log messages; see [baseline/README.md](baseline/README.md). `baseline/server.py` exposes its tools over MCP for Claude Desktop or any other MCP client.
