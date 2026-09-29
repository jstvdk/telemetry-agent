"""ADR-0006 contract: the MCP server exposes exactly the registry's tools, with the same
descriptions and parameters, all read-only, and calls land in the same implementation."""

import asyncio
import json

from shiftassist.mcp_server import build_server
from shiftassist.tools import REGISTRY, Snapshot
from tests.tools.test_tools import snap as snap  # fixture


def test_mcp_list_tools_matches_registry(snap: Snapshot) -> None:
    listed = {t.name: t for t in asyncio.run(build_server(snap).list_tools())}
    assert set(listed) == set(REGISTRY)
    for name, t in REGISTRY.items():
        m = listed[name]
        mine, theirs = t.input_schema(), m.input_schema
        assert m.description == t.description, name
        assert set(theirs.get("properties", {})) == set(mine.get("properties", {})), name
        assert set(theirs.get("required", [])) == set(mine.get("required", [])), name
        for prop, spec in mine.get("properties", {}).items():
            assert theirs["properties"][prop].get("description") == spec.get("description"), (
                name,
                prop,
            )
        assert m.annotations is not None and m.annotations.read_only_hint is True


def test_mcp_call_gives_the_registry_result(snap: Snapshot) -> None:
    server = build_server(snap)
    out = asyncio.run(server.call_tool("query_timeline", {"kind": "restart"}))
    text = json.dumps(out, default=str)
    assert (
        REGISTRY["query_timeline"].call(snap, {"kind": "restart"})[:60].replace('"', '\\"') in text
    )


def test_no_runbook_configuration(snap: Snapshot) -> None:
    names = {t.name for t in asyncio.run(build_server(snap, use_runbook=False).list_tools())}
    assert "search_runbook" not in names and "query_timeline" in names
