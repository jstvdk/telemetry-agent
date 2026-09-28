# ADR-0002 · Deterministic detection; the LLM does language work only

**Status:** Accepted

## Context
The v0 spike gave the model raw log lines and a keyword counter. On a four-line test with one real error, `count_keywords()` returned 3, because substring matching also caught `error_count=0` and `NO_ERROR` ([06](../06-v0-spike-review.md)). The model then reports that number with confidence. Trends over thousands of samples are worse: the model cannot compute a slope reliably from a text dump, and the dump costs thousands of tokens.

## Decision
- **Detection is code:** limit rules with hysteresis, rate-of-change over rolling windows, heartbeat gaps, restart/config/traceback detectors, and a template-based new-signature detector. Each rule has an ID and unit tests.
- Detection emits **events** with IDs, a code-written summary and machine-readable evidence.
- The LLM receives events and **computed features** (slope, z-score, min/max), never raw series.
- The LLM's job: read tracebacks and free text, link events into a cause hypothesis, map them to runbook sections, and write.

## Consequences
- Detection recall and false-alert rate can be measured without any LLM, and must be good before the LLM layer matters.
- The deterministic core alone is a useful product: events plus a template shift log. This is the fallback.
- Rules need maintenance. Rule IDs and scenario tests keep that manageable.

## Alternatives rejected
- **LLM as detector** (scan windows of logs and ask "anything wrong?"): no guarantees, cost scales with data volume, and it cannot be regression-tested cheaply.
- **ML anomaly detection as the main detector:** possible later for unknown unknowns, next to the rules, not instead of them. It needs labelled data first, which the simulator and incident library provide.
