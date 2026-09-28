# ADR-0007 · Provider interface; the model is a config value

**Status:** Accepted

## Context
Target deployments may forbid sending data to a hosted API, so the system must run on local open-weight models. Hosted frontier models are still the best **quality ceiling** during development: if a frontier model fails a test case, the problem is design or data, not model size. Models change every few months.

## Decision
- A small interface: `complete(system, messages, tools) -> Turn(text, tool_calls, stop_reason, usage, latency_ms)`, with messages in a neutral internal format.
- Two adapters:
  - **Anthropic** Messages API, with prompt caching on the system prompt and tool definitions;
  - **OpenAI-compatible** Chat Completions, which covers Ollama, vLLM, llama.cpp server and academic hosting services.
- A **fake provider** that replays scripted turns, used in unit tests and CI.
- Model, provider and endpoint are set in a config file per eval run.

## Consequences
- The same eval runs across hosted and local models. The comparison is the result.
- Tool calling differs between providers (parallel calls, JSON strictness). The adapters handle it, and the eval measures schema-valid rates per model.
- Provider-specific features (caching, extended thinking) are optional per adapter and switched on by config.

## Alternatives rejected
- **A third-party abstraction library** (e.g. LiteLLM): a reasonable choice, but it hides usage and caching details that this project measures. Revisit if more providers are added.
