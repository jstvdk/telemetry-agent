"""Read-only query functions over the stored messages. Shared by the MCP server and the agent."""
import sqlite3
from datetime import datetime
from pathlib import Path

DB = Path(__file__).parent / "telemetry.db"
MAX_TEXT = 300    # characters per message returned; keeps token usage under control
MAX_LIMIT = 200   # hard cap on messages per call


def _query(sql, args=()):
    con = sqlite3.connect(DB)
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


def _now():
    # "Now" = newest stored message, so a frozen snapshot gives reproducible answers.
    return _query("SELECT MAX(ts) FROM messages")[0][0] or 0.0


def list_topics(since_minutes: int = 60) -> dict:
    t0 = _now() - since_minutes * 60
    rows = _query(
        "SELECT topic, COUNT(*) FROM messages WHERE ts >= ? GROUP BY topic ORDER BY 2 DESC", (t0,)
    )
    return {"since_minutes": since_minutes, "topics": [{"topic": t, "count": c} for t, c in rows]}


def get_recent_messages(topic: str | None = None, since_minutes: int = 10,
                        contains: str | None = None, limit: int = 50) -> list[dict]:
    sql, args = "SELECT ts, topic, text FROM messages WHERE ts >= ?", [_now() - since_minutes * 60]
    if topic:
        sql += " AND topic = ?"
        args.append(topic)
    if contains:
        sql += " AND text LIKE ?"
        args.append(f"%{contains}%")
    sql += " ORDER BY ts DESC LIMIT ?"
    args.append(min(int(limit), MAX_LIMIT))
    return [
        {"time": datetime.fromtimestamp(ts).strftime("%H:%M:%S"), "topic": tp, "text": tx[:MAX_TEXT]}
        for ts, tp, tx in _query(sql, args)
    ]


def count_keywords(keywords: list[str] | None = None, since_minutes: int = 60) -> dict:
    keywords = keywords or ["ERROR", "WARN"]
    t0 = _now() - since_minutes * 60
    return {
        k: _query("SELECT COUNT(*) FROM messages WHERE ts >= ? AND text LIKE ?", (t0, f"%{k}%"))[0][0]
        for k in keywords
    }
