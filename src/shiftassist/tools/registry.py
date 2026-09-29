"""One registry for every tool the LLM layer can call (ADR-0006).

A tool is a typed function ``fn(snap, **params) -> dict`` registered once with ``@tool``. The input
schema is generated from its type hints (``Annotated[..., Field(description=...)]``), the
description from its docstring. The agent and the MCP server both read their tool lists from here,
so the model sees the same text whichever client it is used from.

Every tool is read-only: it gets a ``Snapshot`` (frozen capture + events + runbook) and nothing
that can write. Output is JSON, capped at ``max_output_chars``; when the cap is hit, the longest
list in the result is shortened and ``truncated`` is set, so the model knows it saw a part.
"""

import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, get_type_hints

from pydantic import BaseModel, ValidationError, create_model

ToolFn = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    fn: ToolFn
    params: type[BaseModel]
    max_output_chars: int
    read_only: bool = True

    def input_schema(self) -> dict[str, Any]:
        s = self.params.model_json_schema()
        s.pop("title", None)
        return s

    def call(self, snap: Any, args: dict[str, Any]) -> str:
        """Validate, run, serialise, cap. Errors come back as JSON the model can read."""
        try:
            p = self.params.model_validate(args)
        except ValidationError as e:
            return json.dumps(
                {"error": "invalid arguments", "details": e.errors(include_url=False)}
            )
        try:
            out = self.fn(snap, **p.model_dump())
        except LookupError as e:  # unknown id / channel: tell the model, do not crash the loop
            return json.dumps({"error": str(e.args[0] if e.args else e)})
        return cap_output(out, self.max_output_chars)


def cap_output(out: dict[str, Any], limit: int) -> str:
    text = json.dumps(out, default=str)
    if len(text) <= limit:
        return text
    out = dict(out)
    out["truncated"] = True
    while len(text) > limit:
        lists = [k for k, v in out.items() if isinstance(v, list) and v]
        if not lists:
            return text[: limit - 20] + '..."truncated"}'
        k = max(lists, key=lambda k: len(json.dumps(out[k], default=str)))
        out[k] = out[k][: len(out[k]) // 2]
        text = json.dumps(out, default=str)
    return text


REGISTRY: dict[str, Tool] = {}


def tool(max_output_chars: int = 8000) -> Callable[[ToolFn], ToolFn]:
    """Register ``fn(snap, **params)``. The first parameter (the snapshot) is not in the schema."""

    def deco(fn: ToolFn) -> ToolFn:
        hints = get_type_hints(fn, include_extras=True)
        fields: dict[str, Any] = {}
        for i, (name, prm) in enumerate(inspect.signature(fn).parameters.items()):
            if i == 0:
                continue
            default = ... if prm.default is inspect.Parameter.empty else prm.default
            fields[name] = (hints[name], default)
        params = create_model(f"{fn.__name__}_params", **fields)
        doc = inspect.cleandoc(fn.__doc__ or "")
        REGISTRY[fn.__name__] = Tool(fn.__name__, doc, fn, params, max_output_chars)
        return fn

    return deco


def anthropic_tools(names: list[str] | None = None) -> list[dict[str, Any]]:
    """Tool list in the Anthropic Messages API format."""
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema()}
        for t in REGISTRY.values()
        if names is None or t.name in names
    ]


def openai_tools(names: list[str] | None = None) -> list[dict[str, Any]]:
    """Tool list in the OpenAI-compatible chat format (Ollama, vLLM, ...)."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema(),
            },
        }
        for t in REGISTRY.values()
        if names is None or t.name in names
    ]
