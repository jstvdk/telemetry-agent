# Provenance

A dated record of how this project was built: every step, the decisions taken at each one, and the things that went wrong. It is updated as work happens, not rewritten afterwards. [00 · Journey](00-journey.md) tells the story; this file is the evidence behind it.

**Conventions**
- Entries are append-only. A reversed decision gets a new entry that refers to the old one.
- **D-** = decision, **X-** = failure or dead end, **→ ADR** = where the decision is written up in full.
- *Evidence* points at something checkable: a commit, a file, a test, or a command with its output.

---

## Timeline

| Entry | Date | Step | Outcome | Commit / tag |
|---|---|---|---|---|
| [P-00](#p-00--brainstorm) | before 2026-09-25 | Brainstorm | Wish list; core use case found | — (private notes) |
| [P-01](#p-01--structured-roadmap) | ≤ 2026-09-25 | Structured roadmap | Principles, layers, scope cuts | — (private notes) |
| [P-02](#p-02--learning-spike-plan) | 2026-09-27 | Learning-spike plan | Two-evening plan to learn the mechanics | — (private notes) |
| [P-03](#p-03--learning-spike-v0) | 2026-09-27 | Learning spike (v0) | Working loop + MCP; naive by design | `v0-spike` |
| [P-04](#p-04--spike-review) | 2026-09-28 | Spike review | 17 findings, 3 high severity, measured | docs commit |
| [P-05](#p-05--design-documentation) | 2026-09-28 | Design docs | Rationale, requirements, architecture, 8 ADRs, eval + test plan | docs commit |
| [P-06](#p-06--repository-foundations-m0) | 2026-09-28 | M0 repo foundations | git, packaging, baseline/, CI | M0 commit |
| [P-07](#p-07--simulator-m1) | 2026-09-28 | M1 simulator | Seeded scenarios with ground-truth labels | M1 commits |

---

## P-00 · Brainstorm

**Goal.** Write down what an operator assistant for a telescope camera could do.

**Done.** A free-form list: scan all subsystems, detect violations and trends, propose fixes (code fix, reload, config change), write shift logs; six or more specialised agents; cover the camera, telescope structure, weather, pointing and transient-alert scheduling.

**Decisions**
- **D-00a** The operator always takes the final decision. This was the first line of the notes and has held since.
- **D-00b** The first real use case is **explaining a failure before data taking**, using the team's past incidents and code. It came from the operator's own experience: read the traceback, paste it into a generic chatbot, search, ask an expert.
- **D-00c** Defer telescope structure monitoring and transient alerts/scheduling: other teams own them.

**Failures / dead ends**
- **X-00a Over-scoped.** Actions on hardware and software, six agents, five external systems. None of it came with a way to test whether it worked. Fixed in P-01.

**Evidence.** Private notebook (not published: contains institutional details).

---

## P-01 · Structured roadmap

**Goal.** Turn the wish list into something buildable and defensible.

**Method.** One question asked of every brainstorm item: *does this need a guarantee, or does it need language?*

**Decisions**
- **D-01a** Read-only by construction; mitigations as text only. → [ADR-0001](adr/0001-read-only-by-construction.md)
- **D-01b** Detection is deterministic; the LLM explains, correlates and writes. → [ADR-0002](adr/0002-deterministic-detection-llm-for-language.md)
- **D-01c** Six agents collapsed to one agent loop plus fixed pipelines. → [ADR-0003](adr/0003-pipelines-first-one-agent-loop.md)
- **D-01d** No model training; knowledge lives in reviewable files (runbook with `verified` / `ai-draft` status, incident library).
- **D-01e** Every claim must cite evidence, and code checks it. → [ADR-0005](adr/0005-grounding-validator.md)
- **D-01f** Model-agnostic; must run on a local open-weight model on site. → [ADR-0007](adr/0007-model-agnostic-provider-interface.md)
- **D-01g** The labelled incident library, not any model, is the long-lived asset.
- **D-01h** Fallback: if the LLM layer slips, detection plus an auto-generated shift log is still useful.

**Failures / dead ends**
- **X-01a No hands-on experience yet** with tool calling, MCP or token costs, so the roadmap's cost and effort estimates were guesses. This is why P-02 exists.

**Evidence.** Private roadmap (same reason). Its public content is in [01](01-rationale.md), [02](02-requirements.md) and [03](03-architecture.md).

---

## P-02 · Learning-spike plan

**Goal.** Learn the mechanics before building the real thing: tool calling, the agent loop, MCP, and token and cost measurement. Time box: two evenings.

**Decisions**
- **D-02a** Build the agent loop **without a framework**, to see what frameworks hide.
- **D-02b** Collector + SQLite instead of reading the stream directly: an agent needs history.
- **D-02c** "Now" = newest stored record, so a frozen snapshot gives reproducible answers.
- **D-02d** Cap tool output (characters per message, messages per call, characters per result): tool output is resent as input tokens at every step.
- **D-02e** Only mock data and own code in the repo.

**Failures / dead ends.** None at planning time. The plan knowingly accepted a naive tool design (raw text, keyword counts) to keep it to two evenings.

---

## P-03 · Learning spike (v0)

**Goal.** Execute P-02.

**Done.** `collector.py`, `tools.py`, `server.py` (MCP), `agent.py` (loop + usage log), `eval.py`, `analyze.py`, `questions.jsonl` (2 placeholder items). Used from the Claude desktop app over MCP and from the CLI agent.

**Learned**
- The whole agent is ~30 lines: call model → run requested tools → append results → repeat.
- Input tokens grow at every step because the full context is resent. Output caps are the main cost lever.
- MCP separates tools from clients: the same functions worked in the desktop app and in the hand-written loop.

**Failures / dead ends** (found in P-04, listed here because this is where they were introduced)
- **X-03a** Keyword counting over raw text gives wrong numbers (F1).
- **X-03b** The spike depends on an external mock stream that is not in the repo, and the question set has no real expected answers, so nobody else can run or score it (F2, F3).
- **X-03c** Tool definitions are written three times and already differ (F7).

**Evidence.** Tag `v0-spike`: code committed unchanged before any refactor.

---

## P-04 · Spike review

**Goal.** Judge v0 against the roadmap's own principles before building on it.

**Method.** Read every file; reproduce suspected defects in a scratch environment instead of guessing; check the MCP API against the installed SDK version.

**Findings.** 17 in total, 3 high severity; full table in [06](06-v0-spike-review.md). Measured:

| Check | Command / setup | Result |
|---|---|---|
| Keyword count | 4-row DB: `error_count=0`, `ERROR buffer overflow`, `NO_ERROR flag set`, `WARNING …`; `tools.count_keywords()` | `{'ERROR': 3, 'WARN': 1}`; truth is 1 and 1 |
| Missing DB | `tools.list_topics()` with no DB file | `OperationalError: no such table: messages`, and an empty `telemetry.db` is created as a side effect |
| Result truncation | `json.loads(json.dumps(big)[:8000])` | `JSONDecodeError`: the model receives invalid JSON |
| MCP API | `from mcp.server.mcpserver import MCPServer` on `mcp` 2.2.0 | Works. `FastMCP` import fails on 2.x; v0 was already correct |

**Decisions**
- **D-04a Keep v0 as the baseline** for experiment E1 instead of deleting it. The comparison *naive tools vs. structured events on the same model* is the most informative experiment available.
- **D-04b Build a vertical slice next** (thin version of every layer) rather than deepening any single layer.
- **D-04c Replace the external stream with an in-repo simulator** that writes its own ground truth. → [ADR-0004](adr/0004-synthetic-simulator-as-ground-truth.md)

**Failures / dead ends**
- **X-04a** The spike's eval could never have produced trustworthy numbers: manual scoring, one trial per question, prices unset (cost always NaN). Caught before any model comparison was reported.

---

## P-05 · Design documentation

**Goal.** Write down the design *before* the v1 code, so each piece of code implements a decision that is already on record.

**Done.** [01 rationale](01-rationale.md), [02 requirements](02-requirements.md) (7 use cases, FR/NFR, acceptance criteria), [03 architecture](03-architecture.md) (data model, tool contract, answer schema, sequence), [8 ADRs](adr/README.md), [04 evaluation](04-evaluation.md) (6 metric layers, 5 experiments, statistics), [05 test plan](05-test-plan.md) (~40 test cases), [07 delivery plan](07-delivery-plan.md).

**Decisions**
- **D-05a Single tool registry** generates MCP and agent schemas. → [ADR-0006](adr/0006-single-tool-registry-mcp.md)
- **D-05b Structured final answer** via a `submit_answer` tool, so answers are machine-checkable.
- **D-05c Headline reliability metric is pass^k** (right in all k runs), not pass@1. An operator needs consistency.
- **D-05d The LLM judge is calibrated** against 30 hand-scored answers before its scores are used (κ ≥ 0.6).
- **D-05e Accuracy targets are set after the first baseline run**, not guessed in advance. Only detection and grounding have fixed targets, because they are guaranteed by construction.
- **D-05f Private notes stay private.** `internal_docs/` is git-ignored. Public docs contain no institution names, colleagues, policy or funding details.
- **D-05g Status markers** (✅ / 🔨 / 📐) on every component, so no document claims something works before it does.

**Failures / dead ends.** None yet. Risk noted: the docs describe a system that does not exist yet. Mitigation: D-05g, and the status markers are updated in the same commit as the code.

---

## P-06 · Repository foundations (M0)

**Goal.** A repo that anyone can clone, install and test with one command.

**Decisions**
- **D-06a Commit v0 unchanged first, then tag it** (`v0-spike`), then refactor. The history shows the real starting point.
- **D-06b Repo-local git identity** (personal address) for this project, separate from work identity.
- **D-06c uv + `pyproject.toml`, Python 3.12**, `src/` layout. 3.12 rather than the machine's 3.14: wide wheel availability for `pyzmq` and scientific packages, and pinned by uv, so it doesn't depend on the host Python.
- **D-06d v0 moves to `baseline/`** unchanged apart from the move; runnable as before.

*(Failures and evidence for P-06 and P-07 are recorded below as the work happens.)*

---

## P-07 · Simulator (M1)

**Goal.** Seeded scenarios that generate logs and telemetry with ground-truth labels, on the same ZMQ interface v0 used.

*(in progress)*

---

## Failure register

Every failure in one table, with how it was found and where it was resolved. "Found by" matters: a failure found by a test or a measurement is worth more than one found by reading.

| ID | Introduced | Found | Found by | Failure | Impact | Resolution | Status |
|---|---|---|---|---|---|---|---|
| X-00a | P-00 | P-01 | Design review | Scope included actions, 6 agents, 5 external systems | Unbuildable, untestable | Scope cuts D-01a…D-01c | Resolved |
| X-01a | P-01 | P-01 | Self-assessment | No hands-on data on cost or effort | Estimates were guesses | Learning spike P-02/P-03 | Resolved |
| X-03a | P-03 | P-04 | Measurement | Substring keyword counts (3 vs. 1) | Confident wrong numbers | Levels as fields + deterministic events (M2); test T-DET-06 | Open → M2 |
| X-03b | P-03 | P-04 | Review | External stream; no ground truth | Not reproducible or scorable | Simulator (M1) | Open → M1 |
| X-03c | P-03 | P-04 | Review | Tool schemas in 3 places, already drifting | Agent and MCP results not comparable | Single registry (M3) | Open → M3 |
| X-04a | P-03 | P-04 | Review | Eval: manual scoring, k=1, cost NaN | No trustworthy numbers | Eval harness (M4) | Open → M4 |

## Decision register

| ID | Decision | Step | Written up in |
|---|---|---|---|
| D-00a | Operator always decides | P-00 | [01](01-rationale.md) |
| D-00b | Core use case: explain a failure from team history | P-00 | [00](00-journey.md), [02 UC-01](02-requirements.md) |
| D-01a | Read-only by construction | P-01 | [ADR-0001](adr/0001-read-only-by-construction.md) |
| D-01b | Deterministic detection, LLM for language | P-01 | [ADR-0002](adr/0002-deterministic-detection-llm-for-language.md) |
| D-01c | Pipelines + one agent loop | P-01 | [ADR-0003](adr/0003-pipelines-first-one-agent-loop.md) |
| D-01e | Grounding validator | P-01 | [ADR-0005](adr/0005-grounding-validator.md) |
| D-01f | Model-agnostic, local-capable | P-01 | [ADR-0007](adr/0007-model-agnostic-provider-interface.md) |
| D-02b | SQLite collector + snapshots | P-02 | [ADR-0008](adr/0008-sqlite-timeline.md) |
| D-04a | Keep v0 as E1 baseline | P-04 | [04 E1](04-evaluation.md#3-experiments) |
| D-04c | In-repo simulator as ground truth | P-04 | [ADR-0004](adr/0004-synthetic-simulator-as-ground-truth.md) |
| D-05a | Single tool registry | P-05 | [ADR-0006](adr/0006-single-tool-registry-mcp.md) |
| D-05c | pass^k as headline reliability | P-05 | [04 §1](04-evaluation.md#layer-6--consistency) |
| D-05d | Judge calibration before use | P-05 | [04 §1](04-evaluation.md#layer-3--answer-quality-scored-by-question-type) |

---

## Tools and assistance

- **Brainstorm and roadmap (P-00, P-01):** written by the author. Frontier chat models were used to discuss and restructure drafts.
- **P-04 onwards:** Claude Code (Claude Opus) was used as a build-time tool, as the roadmap intends: reviewing the spike, reproducing defects, drafting docs and ADRs, writing code and tests. Scope, design decisions and acceptance were the author's. Commits made with assistance carry a `Co-Authored-By` trailer.
- **Run time:** no model is part of the deterministic core. The LLM layer is configurable ([ADR-0007](adr/0007-model-agnostic-provider-interface.md)).
