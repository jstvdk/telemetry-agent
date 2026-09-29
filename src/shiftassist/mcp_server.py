"""MCP server over one snapshot, generated from the tool registry (ADR-0006).

    shiftassist-mcp CAPTURE [--profile PROFILE] [--runbook DIR] [--no-runbook]

Any MCP client (Claude Desktop, Claude Code, ...) gets the same tools, with the same descriptions
and schemas, as the built-in agent. Every tool is annotated read-only.
"""

import argparse
import inspect
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from shiftassist.agent.loop import RUNBOOK_TOOLS
from shiftassist.tools import REGISTRY, Snapshot
from shiftassist.tools.registry import Tool


def _wrapper(t: Tool, snap: Snapshot) -> Any:
    """A function whose signature is the tool's parameters (without the snapshot)."""

    def fn(**kwargs: Any) -> str:
        return t.call(snap, kwargs)

    params = [
        inspect.Parameter(
            name,
            inspect.Parameter.KEYWORD_ONLY,
            default=inspect.Parameter.empty if f.is_required() else f.default,
            annotation=Annotated[f.annotation, f],
        )
        for name, f in t.params.model_fields.items()
    ]
    fn.__signature__ = inspect.Signature(params, return_annotation=str)  # type: ignore[attr-defined]
    fn.__name__ = t.name
    return fn


def build_server(snap: Snapshot, use_runbook: bool = True) -> MCPServer:
    server = MCPServer(
        "shiftassist",
        instructions=(
            f"Read-only tools over camera snapshot {snap.camera}. Cite event IDs (EV-…) and "
            "runbook entries (RB-…) exactly as returned."
        ),
    )
    for t in REGISTRY.values():
        if not use_runbook and t.name in RUNBOOK_TOOLS:
            continue
        server.add_tool(
            _wrapper(t, snap),
            name=t.name,
            description=t.description,
            annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
        )
    return server


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="shiftassist-mcp", description=__doc__)
    p.add_argument("capture")
    p.add_argument("--profile")
    p.add_argument("--runbook")
    p.add_argument("--no-runbook", action="store_true")
    a = p.parse_args(argv)
    kw: dict[str, Any] = {"profile": a.profile}
    if a.runbook:
        kw["runbook"] = a.runbook
    snap = Snapshot(a.capture, **kw)
    build_server(snap, use_runbook=not a.no_runbook).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
