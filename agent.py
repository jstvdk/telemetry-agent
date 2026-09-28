"""Minimal agent loop: model asks for tools, we run them, repeat until a final answer.
Logs token usage of every API call to usage.csv."""
import csv
import json
import sys
import time
from pathlib import Path

import anthropic

import tools

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
USAGE_CSV = Path(__file__).parent / "usage.csv"
MAX_STEPS = 8          # safety cap on the loop
MAX_RESULT_CHARS = 8000  # cap on each tool result sent back to the model

SYSTEM = (
    "You are a shift assistant for a telescope camera. You can only read monitoring data "
    "through the provided tools. Be concise, cite times and topics, and say so if the data "
    "doesn't answer the question."
)

TOOLS = [
    {
        "name": "list_topics",
        "description": "List message topics/sources seen recently, with message counts.",
        "input_schema": {
            "type": "object",
            "properties": {"since_minutes": {"type": "integer", "description": "Look-back window, default 60"}},
        },
    },
    {
        "name": "get_recent_messages",
        "description": "Return recent log messages, newest first. Filter by topic and/or text (case-insensitive).",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "since_minutes": {"type": "integer", "description": "Default 10"},
                "contains": {"type": "string", "description": "Substring to search for, e.g. ERROR"},
                "limit": {"type": "integer", "description": "Max messages, default 50, max 200"},
            },
        },
    },
    {
        "name": "count_keywords",
        "description": "Count messages containing each keyword (default ERROR, WARN) in a time window.",
        "input_schema": {
            "type": "object",
            "properties": {
                "keywords": {"type": "array", "items": {"type": "string"}},
                "since_minutes": {"type": "integer", "description": "Default 60"},
            },
        },
    },
]

FUNCTIONS = {
    "list_topics": tools.list_topics,
    "get_recent_messages": tools.get_recent_messages,
    "count_keywords": tools.count_keywords,
}


def log_usage(run_id, model, step, usage):
    new_file = not USAGE_CSV.exists()
    with open(USAGE_CSV, "a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["run_id", "model", "step", "input_tokens", "output_tokens",
                        "cache_write_tokens", "cache_read_tokens"])
        w.writerow([run_id, model, step, usage.input_tokens, usage.output_tokens,
                    getattr(usage, "cache_creation_input_tokens", 0) or 0,
                    getattr(usage, "cache_read_input_tokens", 0) or 0])


def run(question, model=DEFAULT_MODEL, run_id=None, client=None, verbose=True):
    client = client or anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    run_id = run_id or f"run-{int(time.time())}"
    messages = [{"role": "user", "content": question}]

    for step in range(MAX_STEPS):
        resp = client.messages.create(model=model, max_tokens=1024, system=SYSTEM,
                                      tools=TOOLS, messages=messages)
        log_usage(run_id, model, step, resp.usage)
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason != "tool_use":  # model is done
            return "".join(b.text for b in resp.content if b.type == "text")

        results = []
        for block in resp.content:
            if block.type == "tool_use":
                if verbose:
                    print(f"  [step {step}] {block.name}({block.input})")
                try:
                    output = json.dumps(FUNCTIONS[block.name](**block.input))
                except Exception as e:  # report tool errors back to the model instead of crashing
                    output = f"ERROR: {e}"
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": output[:MAX_RESULT_CHARS]})
        messages.append({"role": "user", "content": results})

    return "[stopped: reached MAX_STEPS]"


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "Were there any problems in the last hour?"
    m = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_MODEL
    print(run(q, m))
