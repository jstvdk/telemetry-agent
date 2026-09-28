# 06 · v0 spike review

**Scope:** `collector.py`, `tools.py`, `server.py`, `agent.py`, `eval.py`, `analyze.py`, `questions.jsonl`, as written during the two-evening learning spike ([00 · Stage 2](00-journey.md#stage-2--learning-spike-v0)).

**Verdict:** the spike did its job. It shows the whole mechanism (MCP server, bare agent loop, token logging, model comparison) in under 300 lines. It is **not** a base to build on as it is: it breaks the project's own design principles, it cannot run without an external service, and its eval cannot produce trustworthy numbers yet. It stays in the repo as the **baseline** for experiment E1.

## What works

- The agent loop in `agent.py` is correct and minimal: tool errors go back to the model instead of crashing the process, there is a step cap, and usage is logged per call, including cache tokens.
- Tool output caps (`MAX_TEXT`, `MAX_LIMIT`, `MAX_RESULT_CHARS`) put the main cost lever in the right place.
- `_now()` = newest stored record makes time-relative questions reproducible on a frozen snapshot. The idea is kept in v1.
- `server.py` uses the current MCP SDK API (`mcp.server.mcpserver.MCPServer`, verified against `mcp` 2.2.0).
- The same `tools.py` functions back both MCP and the agent.

## Findings

Severity: **High** = gives wrong answers or blocks the demo · **Medium** = will cause wrong results or drift soon · **Low** = hygiene.

| # | Sev. | Finding | Evidence | Fix (milestone) |
|---|---|---|---|---|
| F1 | High | **Keyword counts are wrong.** `count_keywords` uses `LIKE '%ERROR%'`, which matches `error_count=0` and `NO_ERROR` (SQLite `LIKE` is case-insensitive for ASCII) | Measured on a 4-row DB with 1 real error: returned `{'ERROR': 3, 'WARN': 1}` | Parse `level` as a field in the collector; detection emits events; count events, not substrings. Test T-DET-06 (M2) |
| F2 | High | **Not runnable by anyone else.** Needs an external mock ZMQ stream that is not in the repo; `questions.jsonl` expected answers are `"FILL IN"` | `questions.jsonl` lines 1–2 | In-repo simulator + generated labels (M1) |
| F3 | High | **No ground truth, manual scoring.** `eval.py` writes an empty `correct` column to fill in by hand; one trial per question | `eval.py` line 19 | Typed scorers, k = 3 trials, report (M4) |
| F4 | Medium | **Ingest time instead of source time.** `time.time()` at receive; message timestamps are lost | `collector.py` line 25 | Parse source ts as UTC; keep ingest ts separately (M2) |
| F5 | Medium | **Ambiguous time output.** Tools return local `HH:MM:SS` without date or zone | `tools.py` line 44 | ISO-8601 UTC everywhere (M2) |
| F6 | Medium | **Tool results truncated mid-JSON.** `output[:8000]` cuts a JSON string, and the model receives invalid JSON | Reproduced: `json.loads(json.dumps(big)[:8000])` → `JSONDecodeError` | Truncate at record level; add `truncated: true` (M3, T-TL-02) |
| F7 | Medium | **Tool definitions exist three times** (`tools.py`, `server.py` docstrings, `agent.py` JSON schemas) and already differ | Compare descriptions in `server.py` 16–19 vs. `agent.py` 33–45 | Single registry ([ADR-0006](adr/0006-single-tool-registry-mcp.md)) (M3) |
| F8 | Medium | **Hard-coded DB path.** The plan says to copy a snapshot, but tools always read `telemetry.db` | `tools.py` line 6 | DB path from config/env; snapshot-per-scenario (M2) |
| F9 | Medium | **Missing DB gives a confusing error** and creates an empty file as a side effect | Reproduced: `OperationalError: no such table: messages`; empty `telemetry.db` created | Open read-only with `mode=ro` URI; clear error (M2, T-TL-03) |
| F10 | Medium | **`max_tokens` stop treated as a final answer.** Any `stop_reason` other than `tool_use` returns | `agent.py` line 89 | Handle `end_turn`, `max_tokens`, `refusal` explicitly (M3, T-AG-07) |
| F11 | Medium | **LLM answers from raw text, with no citations.** Nothing checks the claims | Design | Events + validator ([ADR-0005](adr/0005-grounding-validator.md)) (M3) |
| F12 | Low | Tool errors are sent as plain text without `is_error: true` | `agent.py` line 100 | Set `is_error` (M3) |
| F13 | Low | No prompt caching on system prompt + tools, which are resent every step | `agent.py` line 84 | `cache_control` on the tools block (M3, experiment E4) |
| F14 | Low | Usage log has no timestamp, latency or tool names | `agent.py` `log_usage` | Extend the schema (M3) |
| F15 | Low | `eval.py` / `analyze.py` do their work at import time; `answers.csv` has no header and duplicates rows on re-runs | `eval.py` 11–20 | `main()`, run IDs, output file per run (M4) |
| F16 | Low | Prices are `None`, so cost is always NaN; cache-token pricing is missing | `analyze.py` 5–8 | Dated price config including cache read/write (M4) |
| F17 | Low | No `pyproject.toml`, lockfile, `.gitignore`, tests, README or git history | repo root | M0 |

## Lessons carried into v1

1. **The architecture needs to be tested, not only the model.** F1 is not a model error. Better prompting cannot fix a wrong number coming from a tool.
2. **A demo that others cannot run does not count as a demo.** A self-contained simulator is worth more than a realistic stream nobody else has.
3. **Scoring by hand does not scale past ~20 answers.** Typed questions with automatic scorers are needed before comparing models.
