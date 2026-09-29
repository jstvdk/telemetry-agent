# Shift Assistant: a read-only LLM agent over instrument telemetry

A prototype **operator assistant** for a telescope camera. It watches logs and telemetry, detects problems with deterministic rules, and uses an LLM to **explain, correlate and write**: answering "why did the readout restart at 02:13?" with citations that code has checked, and drafting the shift log.

> **The LLM never detects and never acts.** Detection is code. Every claim cites an event or runbook section, and a validator checks it. The assistant has no write access to anything.

## Status

| Stage | State |
|---|---|
| v0 learning spike: MCP server, bare agent loop, token logging (files in the repo root) | ✅ done, [reviewed](docs/06-v0-spike-review.md) |
| v1 simulator: 10 seeded fault scenarios with ground-truth labels (`make sim SCENARIO=S03`) | ✅ M1 |
| camera-in-a-box: real camera software on mocks, 9 fault types, labels validated against data | ✅ [lab](lab/camera-in-a-box/README.md) |
| Detector v0: held-out recall 15/16, 0 false alarms on faulted run, 1.3 /h on clean run | ✅ [results](docs/results.md) |
| Detector v1: frozen-gatherer rule, thresholds from a longer clean baseline | 🔨 stall rule done ([P-17](docs/PROVENANCE.md#p-17--a-frozen-gatherer-late-arrival-instead-of-gaps)); thresholds wait for the 3-h baseline |
| Runbook: 11 symptom entries with sources, retrieval tested on real detector events | 🔨 `ai-draft`, awaiting operator review ([runbook](runbook/README.md)) |
| LLM layer: 7 read-only tools (one registry → agent + MCP), agent loop, grounding validator | ✅ built and tested offline; no live model run yet |
| Agent evaluation: questions from labels, layers 2–6, pass^k, a no-LLM rule baseline | ✅ harness; rule baseline names the right runbook entry for 7/8 and 8/10 dev faults |
| Held-out B03 (generated from the runbook-freeze commit) + experiments with models | 📐 protocol fixed ([P-18](docs/PROVENANCE.md#p-18--runbook-draft-and-the-b03-protocol)) |

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

# on a capture from lab/camera-in-a-box (see its README):
uv run shiftassist-detect run CAPTURE -p PROFILE                    # events.jsonl
uv run shiftassist-ask CAPTURE "What happened at 22:13?"            # needs ANTHROPIC_API_KEY
uv run shiftassist-ask CAPTURE "..." --provider openai --model MODEL  # local, e.g. Ollama
uv run shiftassist-eval-agent CAPTURE --map eval/runbook_map.draft.yaml -o out/  # rule baseline
uv run shiftassist-mcp CAPTURE      # the same tools for any MCP client
```

## Repository layout

```
src/shiftassist/    sim · collect · detect · lab (fault harness) · tools · agent · evaluate
lab/camera-in-a-box/  real camera software on mocks in Docker, fault scenarios (tier B)
runbook/            one Markdown entry per symptom, with status and sources
scenarios/          tier-A simulator scenarios (YAML)
eval/               detector profiles, runbook maps
tests/
baseline/           v0 learning spike, unchanged; baseline for experiment E1
docs/               design docs, ADRs, evaluation, provenance
```

v0 needs a ZMQ publisher of log messages; see [baseline/README.md](baseline/README.md). `baseline/server.py` exposes its tools over MCP for Claude Desktop or any other MCP client.
