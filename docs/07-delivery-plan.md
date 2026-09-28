# 07 · Delivery plan

Goal: a **vertical slice** you can run and evaluate, with every roadmap layer present in thin form. Depth comes later. Each milestone ends in a state that runs and has passing tests, so the work can stop at any milestone and still be shown.

| M | Milestone | Deliverables | Exit criterion | Effort |
|---|---|---|---|---|
| **M0** | Repo foundations | `git init` with v0 committed **as-is** and tagged `v0-spike`; move v0 to `baseline/`; `pyproject.toml` (uv, Python 3.12); `.gitignore`; `Makefile`; README; CI skeleton | `make test` runs (no tests yet) in CI; history shows v0 before any refactor | 0.5 day |
| **M1** | Simulator + scenarios | `sim/` with scenario YAML loader, seeded generators, fault injectors, label writer; scenarios S01–S04 first, S05–S10 after | T-SC-SEED passes; a snapshot and labels come out of one command | 1 day |
| **M2** | Deterministic core | Collector with source ts/level/camera; traceback assembler; detection rules + signature miner; `events` table | T-COL-*, T-DET-*, T-SC-S01…S04 pass; recall 1.0, zero alarms on S01 | 1–1.5 days |
| **M3** | LLM layer | Tool registry; MCP server from registry; provider interface (Anthropic, OpenAI-compatible, fake); agent loop with `submit_answer`; validator; prompt caching | T-TL-*, T-VAL-*, T-AG-*, T-MCP-*, T-SAFE-* pass; demo question answered with checked citations | 1.5 days |
| **M4** | Eval harness | Question generator from labels + hand-written items; typed scorers; judge + calibration sheet; runner with k trials; markdown report + scatter plot | `make eval CONFIG=…` produces a full report on the dev set | 1 day |
| **M5** | Experiments | E1 (baseline vs. structured), E2 (models incl. one local), E3 (validator), E4 (caching) on the held-out set | `docs/results.md` written, including failures | 0.5–1 day |
| **M6** | Polish | Shift-log pipeline (UC-05); scenarios S05–S10; README with a recorded demo transcript; docs updated to real status | T-E2E-01/02 pass; a new reader can run `make demo` in < 5 min | 1 day |

**Fallback order if time is short:** M0 → M1 → M2 → M3 (without the validator) → M4 with E1 only. That still shows the key result: *architecture vs. model*, measured.

## Commit discipline

The history is part of what gets shown. One commit per coherent step, with messages that explain *why*, for example:
- `sim: add seeded scenario runner and S01 nominal night`
- `detect: parse level as field; fixes substring over-count (v0 F1)`
- `agent: structured submit_answer + validator V1–V5`

ADRs are committed **before** the code that implements them.

## Demo script (≈ 7 minutes)

1. **Problem** (1 min): a traceback at 3 a.m. and what the operator does today. The Stage 0 note from [00](00-journey.md).
2. **Design choices** (1.5 min): the "LLM vs. code" table, read-only by construction, grounding validator. Show one ADR.
3. **Live run** (2 min): `make demo SCENARIO=S03`. Show the event timeline, then ask *"Why did the readout restart at 02:13?"*. Show the tool calls as they happen and the answer with checked citations. Then ask the distractor question.
4. **Evaluation** (2 min): the E1 table (baseline vs. structured) and the cost-vs-accuracy plot; pass^3; one failure example and what it taught.
5. **What's next** (0.5 min): replay of real logs, shadow mode, local models on site.

## Questions to prepare for

- *Why not LangGraph / an agent framework?* → [ADR-0003](adr/0003-pipelines-first-one-agent-loop.md); a framework port is a planned comparison.
- *How do you know the judge is right?* → calibration against 30 hand-scored answers, κ reported ([04 §1](04-evaluation.md#layer-3--answer-quality-scored-by-question-type)).
- *Isn't synthetic data too easy?* → yes, that risk is written down in [ADR-0004](adr/0004-synthetic-simulator-as-ground-truth.md); mitigations are trap lines, perturbations, and replay of real logs in the same label format.
- *What about prompt injection via logs?* → no write tools exist ([ADR-0001](adr/0001-read-only-by-construction.md)); scenario S10 measures it.
- *How would this scale to 37 telescopes?* → detection per camera; LLM load scales with incidents, not telescopes; S09 tests array-level correlation.
- *What would you do with a bigger budget?* → a larger labelled incident library from real operations; shadow mode; operator feedback loop.
