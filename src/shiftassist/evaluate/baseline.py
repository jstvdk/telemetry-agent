"""A deterministic stand-in for the model: the floor any LLM configuration must beat.

It speaks the same tool protocol as a model, so it runs through the same loop, validator and
scorer: read the timeline for the question window, open the first most severe event, and answer
with that event's first runbook entry that has no extra condition, citing the events it saw. No
reasoning about cause and consequence, no reading of the entry, no checks.
"""

import json
import re
from typing import Any

from shiftassist.agent.providers import Msg, ToolCall, ToolSpec, Turn

SEVERITY = {"alarm": 2, "warning": 1, "info": 0}
WINDOW = re.compile(r"about (\S+Z) to (\S+Z)")


class BaselineProvider:
    name = "rule-baseline"
    model = "first-alarm-first-entry"

    def complete(self, system: str, messages: list[Msg], tools: list[ToolSpec]) -> Turn:
        tool_msgs = [m for m in messages if m["role"] == "tool"]
        if not tool_msgs:
            m = WINDOW.search(messages[0]["text"])
            args = {"start": m.group(1), "end": m.group(2)} if m else {}
            return Turn("", [ToolCall("b1", "query_timeline", args | {"limit": 200})])
        if len(tool_msgs) == 1:
            timeline = json.loads(tool_msgs[0]["results"][0][1])
            events = timeline.get("events", [])
            if not events:
                return self._submit(
                    {
                        "status": "insufficient_data",
                        "answer": "No detector events in the window.",
                        "claims": [],
                    }
                )
            top = max(events, key=lambda e: (SEVERITY[e["severity"]], -events.index(e)))
            return Turn("", [ToolCall("b2", "get_event", {"event_id": top["id"]})])
        timeline = json.loads(tool_msgs[0]["results"][0][1])
        ev = json.loads(tool_msgs[1]["results"][0][1])
        entries = [r["id"] for r in ev.get("runbook", []) if not r.get("applies_if")]
        answer: dict[str, Any] = {
            "status": "answered" if entries else "not_in_runbook",
            "answer": ev["summary"],
            "claims": [{"text": e["summary"], "citations": [e["id"]]} for e in timeline["events"]][
                :20
            ],
            "runbook_entry": entries[0] if entries else None,
        }
        if entries:
            answer["claims"].append({"text": f"See {entries[0]}", "citations": [entries[0]]})
        return self._submit(answer)

    @staticmethod
    def _submit(answer: dict[str, Any]) -> Turn:
        return Turn("", [ToolCall("b9", "submit_answer", answer)])
