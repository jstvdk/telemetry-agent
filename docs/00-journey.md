# 00 · Project journey

How the project got from a page of notes to a system you can evaluate. Every stage has an artifact, and each stage changed the design for a stated reason.

```
Stage 0          Stage 1            Stage 2           Stage 3            Stage 4               Stage 5
Brainstorm  ──▶  Structured    ──▶  Learning     ──▶  Spike        ──▶  Vertical slice   ──▶  Experiments
(notes)          roadmap            spike (v0)        review             (v1)                  + results
                 principles         2 evenings        measured bugs      simulator → agent     A/B, models
✅               ✅                 ✅                ✅                 📐                    📐
```

---

## Stage 0 · Brainstorm

**Starting point:** operating a camera on a telescope array. When a service fails before data taking, the operator reads a traceback, pastes it into a chatbot, searches the wiki and asks an expert. This happens every shift, and it gets worse as the number of telescopes grows while the crew stays the same size.

The first notes were a wish list. The assistant would:
- scan all subsystems continuously;
- detect limit violations and unusual trends;
- propose mitigations, *including code fixes, reloads and config changes*;
- write shift logs automatically;
- be built from many agents: "feature extraction agent, grouping agent, decision agent, notification agent, solution agent, action agent … maybe much less";
- cover the camera, the telescope structure, the weather, pointing and transient-alert scheduling.

The notes ended with the most useful observation of the whole stage:

> *Imagine you start all services to take data and one fails. Today you read the traceback, copy it into a chatbot, google it, ask experts. The assistant could look at a database of runbooks and already-fixed problems, read the code, and give the reason and ideas for a fix.*

That use case, **explaining a failure using the team's own history**, became the core of the project.

## Stage 1 · Structured roadmap: making the decisions

The brainstorm was turned into a roadmap by asking one question of every item: *does this need a guarantee, or does it need language?*

| Brainstorm idea | Decision | Why |
|---|---|---|
| Agent proposes and applies fixes (reload, config change, code fix) | **Removed.** Read-only by construction; suggestions are text only | A wrong action on hardware is expensive and hard to undo. Trust has to be earned in shadow mode first. See [ADR-0001](adr/0001-read-only-by-construction.md) |
| LLM detects violations and trends | **Moved to code.** Rules and rolling statistics detect; the LLM explains | A missed alarm is unacceptable, so detection needs a guarantee. LLMs are poor at arithmetic over long series. See [ADR-0002](adr/0002-deterministic-detection-llm-for-language.md) |
| Six or more specialised agents | **Collapsed** into one agent loop with ~4 tools, plus fixed pipelines | Each extra agent adds failure modes and cost without a measured benefit. Use pipelines where the steps are known. See [ADR-0003](adr/0003-pipelines-first-one-agent-loop.md) |
| Structure monitoring, transient alerts, scheduling | **Deferred** | Other teams own these systems. Start where there is data access and domain knowledge |
| "Train the model on our data" | **No training.** Knowledge lives in files (runbook, incident library) that the model reads at run time | Files can be reviewed, versioned and corrected by a person. Fine-tuned weights cannot |
| Trust the explanation | **Grounding validator:** every claim cites an event ID or runbook section, and code checks it | "Plausible but wrong" is the main documented failure mode of LLM agents in science workflows. See [ADR-0005](adr/0005-grounding-validator.md) |
| — (new) | **Evaluation set as the main asset** | Models change every few months. A labelled incident library outlives any model choice |

The roadmap also fixed the **layers** (collectors → detection → event timeline → LLM with tools → validator → outputs), which are still the architecture in [03](03-architecture.md).

## Stage 2 · Learning spike (v0)

**Goal:** learn the mechanics before building the real thing: tool calling, the agent loop, MCP, and token accounting. Time box: two evenings.

**Built (the code in the repo root):**
- `collector.py`: ZMQ subscriber → SQLite.
- `tools.py`: three read-only queries over raw log text.
- `server.py`: the same tools as an MCP server, used from the Claude desktop app.
- `agent.py`: a hand-written agent loop (no framework) that logs tokens per call.
- `eval.py`, `analyze.py`: run questions against several models; summarize cost and accuracy.

The spike was **deliberately naive**: the model reads raw log lines and counts keywords. The point was to see what frameworks hide, not to build the final design.

**What it taught:**
1. The agent is ~30 lines. Frameworks wrap exactly this loop.
2. Input tokens grow at every step, because the whole context is resent. Capping tool output is the main cost lever.
3. `_now()` = newest stored message makes answers reproducible on a frozen snapshot.
4. MCP separates tools from clients: write the tools once, and any MCP client can call them.

## Stage 3 · Reviewing the spike against the principles

The spike was reviewed against the roadmap's own principles ([06](06-v0-spike-review.md)). Main finding: **it breaks principle 2 ("if it can be an if-statement, it is code")**, and this can be measured. On a four-line test database with one real error, `count_keywords()` returns **ERROR = 3**, because substring matching also counts `error_count=0` and `NO_ERROR`. The LLM would then report a wrong number with confidence.

Two other findings set the next stage:
- The spike depends on an external mock stream that is not in the repo, so nobody else can run it, and there is no ground truth to score against.
- Tool schemas are written three times (`tools.py`, `server.py`, `agent.py`) and will drift apart.

## Stage 4 · Vertical slice (v1) 📐

Build one thin path through **every** layer of the roadmap, end to end, on synthetic data:

1. **Camera simulator** with scripted fault scenarios. Each scenario writes its own ground-truth labels ([ADR-0004](adr/0004-synthetic-simulator-as-ground-truth.md)).
2. **Collector** that keeps source timestamps (UTC) and log levels as fields.
3. **Detection:** limit rules, rate-of-change, heartbeat gaps, new error signatures → events with IDs.
4. **Tool registry:** defined once; generates both the MCP server and the agent's tool schemas ([ADR-0006](adr/0006-single-tool-registry-mcp.md)).
5. **Agent** with a provider interface, so the same loop runs on Anthropic models and on local open-weight models via an OpenAI-compatible API ([ADR-0007](adr/0007-model-agnostic-provider-interface.md)).
6. **Grounding validator** and a structured final answer.
7. **Eval harness** with automatic scoring.

The v0 code is kept as the **baseline** for experiment E1, not thrown away.

## Stage 5 · Experiments 📐

See [04 · Evaluation](04-evaluation.md). The main question:

> Does moving detection into code and giving the LLM events and features, instead of raw logs, improve correctness and grounding, and at what cost in tokens?

Results will be added to `docs/results.md` whatever they show, including negative results.
