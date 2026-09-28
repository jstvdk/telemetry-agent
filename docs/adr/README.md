# Architecture decision records

One file per decision, in the format *Context → Decision → Consequences → Alternatives rejected*. A decision is changed by adding a new ADR that supersedes the old one, never by editing history.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-read-only-by-construction.md) | Read-only by construction, not by prompt | Accepted |
| [0002](0002-deterministic-detection-llm-for-language.md) | Deterministic detection; LLM only for language work | Accepted |
| [0003](0003-pipelines-first-one-agent-loop.md) | Pipelines first; one hand-written agent loop; no framework | Accepted |
| [0004](0004-synthetic-simulator-as-ground-truth.md) | In-repo simulator with fault scenarios as the source of ground truth | Accepted |
| [0005](0005-grounding-validator.md) | Structured final answer + deterministic grounding validator | Accepted |
| [0006](0006-single-tool-registry-mcp.md) | One tool registry generates MCP server and agent schemas | Accepted |
| [0007](0007-model-agnostic-provider-interface.md) | Provider interface; models are config | Accepted |
| [0008](0008-sqlite-timeline.md) | SQLite as the event timeline and snapshot format | Accepted |
