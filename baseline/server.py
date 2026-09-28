"""MCP server exposing the telemetry tools. Runs over stdio: never print() to stdout here."""
from mcp.server.mcpserver import MCPServer

import tools

mcp = MCPServer("sst-telemetry")


@mcp.tool()
def list_topics(since_minutes: int = 60) -> dict:
    """List message topics/sources seen in the last `since_minutes`, with message counts."""
    return tools.list_topics(since_minutes)


@mcp.tool()
def get_recent_messages(topic: str | None = None, since_minutes: int = 10,
                        contains: str | None = None, limit: int = 50) -> list[dict]:
    """Return recent log messages, newest first. Filter by topic and/or text (case-insensitive)."""
    return tools.get_recent_messages(topic, since_minutes, contains, limit)


@mcp.tool()
def count_keywords(keywords: list[str] | None = None, since_minutes: int = 60) -> dict:
    """Count messages containing each keyword (default: ERROR, WARN) in the last `since_minutes`."""
    return tools.count_keywords(keywords, since_minutes)


if __name__ == "__main__":
    mcp.run()  # stdio transport by default
