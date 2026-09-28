# ADR-0005 · Structured final answer + deterministic grounding validator

**Status:** Accepted

## Context
The main failure mode of LLM agents in technical workflows is the confident, plausible, wrong answer. In operations it is worse than no answer. Asking the model to "be careful" does not change that. A check that does not depend on the model does.

## Decision
1. The agent ends by calling `submit_answer` with a **structured answer**: `status`, `answer`, and a list of `claims`. Each claim has `citations` (event IDs, runbook section IDs) and optional numeric `values`.
2. A **validator** (plain code, no LLM) checks each claim:

| Rule | Check | On failure |
|---|---|---|
| V1 | Claim has at least one citation | flag `uncited` |
| V2 | Every citation resolves (event in timeline, section in runbook) | drop claim, count as **hallucinated citation** |
| V3 | Cited event is inside the question's time window | flag `out_of_window` |
| V4 | Numeric `values` match the cited evidence within tolerance | flag `value_mismatch` |
| V5 | Cited runbook section has `status: verified` | flag `unverified_source` (shown, not dropped) |

3. The operator sees the answer with per-claim marks. Flag and drop counts are logged and are eval metrics.

## Consequences
- "Hallucinated citations after validation" can be driven to zero by construction. That is a measurable safety property, not a hope.
- The validator checks that the evidence *exists and matches*, not that the reasoning is right. Reasoning quality is measured separately (rubric scoring in [04](../04-evaluation.md)).
- Structured output is harder for small local models. That is measured too (schema-valid rate), and it is a fair test of whether a model is fit for this job.

## Alternatives rejected
- **LLM-as-verifier** (a second model checks the first): useful as an extra signal later, but it shares the same failure mode.
- **Free-text answers with regex-extracted citations:** fragile, and the model can cite in prose without any structure.
