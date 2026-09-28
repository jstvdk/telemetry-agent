# ADR-0003 · Pipelines first; one hand-written agent loop; no framework

**Status:** Accepted

## Context
The brainstorm listed six or more agents (feature extraction, grouping, decision, notification, solution, action). Each boundary between agents is a place where context is lost, cost is added, and errors compound. Evaluation also gets harder: which agent was wrong?

Some tasks have known steps (the shift log). Others do not: an investigation depends on what the last query found.

## Decision
- **Pipeline** (code decides the steps, the LLM fills one step) for anything with known steps: shift log, new-signature summary.
- **One agent loop** (the model picks the next tool) only for open questions: UC-01 to UC-04.
- The loop is **hand-written** (~50 lines): call model → run requested tools → append results → repeat until `submit_answer` or `MAX_STEPS`.

## Consequences
- Every step is visible and logged: tokens, latency, tool arguments, errors. Nothing is hidden in a framework.
- Swapping models or providers only touches the adapter ([ADR-0007](0007-model-agnostic-provider-interface.md)).
- Missing framework features (tracing UI, checkpoints, retries) are written by hand if needed. So far that is a few lines each.
- A framework port (LangGraph, OpenAI Agents SDK) is a planned *comparison*, not a dependency.

## Alternatives rejected
- **Multi-agent architecture now:** no measured need. Revisit if array-level correlation across many cameras shows one context is not enough.
- **Framework first:** it hides exactly the mechanics (context growth, stop conditions, tool errors) that this project needs to measure.
