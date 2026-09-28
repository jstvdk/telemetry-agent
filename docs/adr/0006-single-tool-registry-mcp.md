# ADR-0006 · One tool registry generates the MCP server and the agent schemas

**Status:** Accepted

## Context
In v0 each tool is described three times: the function signature in `tools.py`, the decorated wrapper and docstring in `server.py`, and a hand-written JSON schema in `agent.py`. They already differ (for example, the default-value descriptions). The model sees different descriptions depending on the client, so an MCP-client result and an agent result are not comparable.

## Decision
- Each tool is a typed Python function with a docstring, registered once with metadata: `name`, `description`, `read_only`, `max_output_chars`.
- The input schema is generated from the type hints (Pydantic).
- The **MCP server** registers the same functions from the registry.
- The **agent** gets its tool list from the registry, converted per provider (Anthropic `input_schema`, OpenAI `function.parameters`).
- A contract test asserts the MCP `list_tools` output matches the registry.

## Consequences
- One place to change a description, which matters because tool descriptions are part of the prompt and affect accuracy.
- The agent still calls tools in-process for speed and simpler tracing. Running it as a real MCP client is a flag, used in one experiment to show both paths give the same results.

## Alternatives rejected
- **Agent always talks to tools over MCP stdio:** cleaner in principle, but adds a process boundary to every eval run with no measured benefit here.
