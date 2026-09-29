"""One interface over model APIs (ADR-0007): Anthropic, and any OpenAI-compatible endpoint
(Ollama, vLLM, llama.cpp server, hosted). The loop only sees ``Turn``s and ``ToolCall``s.

Conversation messages are provider-neutral:
    {"role": "user", "text": str}
    {"role": "assistant", "turn": Turn}
    {"role": "tool", "results": [(call_id, content), ...]}
"""

import json
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

Msg = dict[str, Any]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class Turn:
    text: str
    calls: list[ToolCall]
    usage: dict[str, int] = field(default_factory=dict)


class Provider(Protocol):
    name: str
    model: str

    def complete(self, system: str, messages: list[Msg], tools: list[ToolSpec]) -> Turn: ...


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str = "claude-sonnet-5", max_tokens: int = 2048, client: Any = None):
        import anthropic  # optional dependency: the `llm` extra

        self.model, self.max_tokens = model, max_tokens
        # Any: our neutral messages are converted by _msg; the SDK's TypedDicts are not needed
        self.client: Any = client or anthropic.Anthropic()

    def complete(self, system: str, messages: list[Msg], tools: list[ToolSpec]) -> Turn:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            tools=[
                {"name": t.name, "description": t.description, "input_schema": t.schema}
                for t in tools
            ],
            messages=[self._msg(m) for m in messages],
        )
        from anthropic.types import TextBlock, ToolUseBlock

        text = "".join(b.text for b in resp.content if isinstance(b, TextBlock))
        calls = [
            ToolCall(b.id, b.name, dict(b.input))
            for b in resp.content
            if isinstance(b, ToolUseBlock)
        ]
        u = resp.usage
        return Turn(text, calls, {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens})

    @staticmethod
    def _msg(m: Msg) -> dict[str, Any]:
        if m["role"] == "user":
            return {"role": "user", "content": m["text"]}
        if m["role"] == "assistant":
            t: Turn = m["turn"]
            blocks: list[dict[str, Any]] = [{"type": "text", "text": t.text}] if t.text else []
            blocks += [
                {"type": "tool_use", "id": c.id, "name": c.name, "input": c.args} for c in t.calls
            ]
            return {"role": "assistant", "content": blocks}
        return {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": cid, "content": content}
                for cid, content in m["results"]
            ],
        }


class OpenAICompatProvider:
    """Chat Completions with tools, e.g. Ollama at http://localhost:11434/v1."""

    name = "openai-compatible"

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434/v1",
        api_key: str | None = None,
        timeout_s: float = 300.0,
    ):
        import httpx

        self.model = model
        key = api_key or os.environ.get("OPENAI_API_KEY", "none")
        self.http = httpx.Client(
            base_url=base_url, timeout=timeout_s, headers={"Authorization": f"Bearer {key}"}
        )

    def complete(self, system: str, messages: list[Msg], tools: list[ToolSpec]) -> Turn:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *self._msgs(messages)],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.schema,
                    },
                }
                for t in tools
            ],
        }
        r = self.http.post("/chat/completions", json=body)
        r.raise_for_status()
        data = r.json()
        msg = data["choices"][0]["message"]
        calls = []
        for i, c in enumerate(msg.get("tool_calls") or []):
            args = c["function"].get("arguments") or "{}"
            try:
                parsed = json.loads(args) if isinstance(args, str) else dict(args)
            except json.JSONDecodeError:
                parsed = {"_unparseable_arguments": args}
            calls.append(ToolCall(c.get("id") or f"call_{i}", c["function"]["name"], parsed))
        u = data.get("usage") or {}
        usage = {
            "input_tokens": u.get("prompt_tokens", 0),
            "output_tokens": u.get("completion_tokens", 0),
        }
        return Turn(msg.get("content") or "", calls, usage)

    @staticmethod
    def _msgs(messages: list[Msg]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["text"]})
            elif m["role"] == "assistant":
                t: Turn = m["turn"]
                a: dict[str, Any] = {"role": "assistant", "content": t.text or None}
                if t.calls:
                    a["tool_calls"] = [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {"name": c.name, "arguments": json.dumps(c.args)},
                        }
                        for c in t.calls
                    ]
                out.append(a)
            else:
                out += [
                    {"role": "tool", "tool_call_id": cid, "content": content}
                    for cid, content in m["results"]
                ]
        return out


class ScriptedProvider:
    """A fake model for tests: returns prepared turns in order and records what it was sent."""

    name = "scripted"

    def __init__(self, turns: list[Turn], model: str = "script"):
        self.turns, self.model = list(turns), model
        self.seen: list[tuple[str, list[Msg], list[ToolSpec]]] = []

    def complete(self, system: str, messages: list[Msg], tools: list[ToolSpec]) -> Turn:
        self.seen.append((system, list(messages), tools))
        return self.turns.pop(0) if self.turns else Turn("I am done.", [])
