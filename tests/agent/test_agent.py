"""Agent loop and grounding validator, driven by a scripted model (no network, no cost)."""

import json
from datetime import UTC, datetime

from shiftassist.agent.answer import Answer, Claim
from shiftassist.agent.loop import run, tool_specs
from shiftassist.agent.providers import (
    AnthropicProvider,
    OpenAICompatProvider,
    ScriptedProvider,
    ToolCall,
    Turn,
)
from shiftassist.agent.validator import validate
from shiftassist.tools import Snapshot
from tests.detect.test_rules import T0
from tests.tools.test_tools import snap as snap  # fixture, re-exported for pytest


def _restart(s: Snapshot) -> str:
    return next(e.event_id for e in s.events if e.kind == "restart")


def _submit(**answer: object) -> Turn:
    return Turn("", [ToolCall("s1", "submit_answer", answer)])


def good_answer(ev: str) -> dict[str, object]:
    return {
        "status": "answered",
        "answer": "The slow-signal server crashed once and was restarted by systemd.",
        "claims": [
            {
                "text": "slowsignal exited with status 1 and restarted",
                "citations": [ev],
                "values": {"restarts": 1},
            },
            {"text": "A server restart is covered by the runbook", "citations": ["RB-005"]},
        ],
        "runbook_entry": "RB-005",
        "recommended_checks": ["Read the exception in the traceback."],
    }


def test_full_loop_submits_a_validated_answer(snap: Snapshot) -> None:
    ev = _restart(snap)
    model = ScriptedProvider(
        [
            Turn(
                "Looking at the timeline.", [ToolCall("c1", "query_timeline", {"kind": "restart"})]
            ),
            Turn("", [ToolCall("c2", "get_event", {"event_id": ev})]),
            _submit(**good_answer(ev)),
        ]
    )
    res = run("Why did slow-signal restart?", snap, model)
    assert res.stop == "submitted" and res.answer is not None and res.validation is not None
    assert res.validation.summary()["dropped"] == 0
    assert res.validation.flag_counts == {"unverified_source": 1, "runbook_entry_draft": 1}
    # the model saw the tool results it asked for
    tool_msg = model.seen[1][1][-1]
    assert tool_msg["role"] == "tool" and ev in tool_msg["results"][0][1]


def test_invented_citation_is_dropped_and_counted(snap: Snapshot) -> None:
    ans = Answer.model_validate(good_answer(_restart(snap)))
    ans.claims.append(Claim(text="A config reload preceded it", citations=["EV-424242"]))
    v = validate(ans, snap)
    assert v.hallucinated_citations == 1 and len(v.kept) == 2
    assert v.checks[-1].dropped


def test_values_are_checked_against_what_is_cited(snap: Snapshot) -> None:
    ev = _restart(snap)
    wrong = Answer.model_validate(good_answer(ev))
    wrong.claims[0].values = {"restarts": 7}
    assert "value_mismatch" in validate(wrong, snap).checks[0].flags
    # a telemetry window citation is recomputed by the validator
    a = datetime.fromtimestamp(T0 + 500, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    b = datetime.fromtimestamp(T0 + 900, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    cit = f"telemetry:slowsignal/tm03/temperature_sipm1@{a}/{b}"
    claim = Claim(
        text="tm03 warms ~12 °C/h faster than the others",
        citations=[cit],
        values={"relative_slope_per_h": 12.0},
    )
    ok = Answer(status="answered", answer="x", claims=[claim])
    assert validate(ok, snap).checks[0].flags == []
    bad = ok.model_copy(deep=True)
    bad.claims[0].values = {"relative_slope_per_h": 40.0}
    assert validate(bad, snap).checks[0].flags == ["value_mismatch"]
    nosuch = ok.model_copy(deep=True)
    nosuch.claims[0].citations = [cit.replace("tm03", "tm99")]
    assert validate(nosuch, snap).checks[0].dropped


def test_out_of_window_and_uncited_are_flagged(snap: Snapshot) -> None:
    ans = Answer.model_validate(good_answer(_restart(snap)))
    ans.claims.append(Claim(text="Everything else was normal", citations=[]))
    late = (datetime.fromtimestamp(T0 + 1000, UTC), datetime.fromtimestamp(T0 + 1100, UTC))
    v = validate(ans, snap, late)
    assert "out_of_window" in v.checks[0].flags and v.checks[-1].flags == ["uncited"]


def test_schema_error_is_returned_and_the_model_can_retry(snap: Snapshot) -> None:
    model = ScriptedProvider(
        [_submit(status="maybe", answer="?"), _submit(**good_answer(_restart(snap)))]
    )
    res = run("q", snap, model)
    assert res.stop == "submitted" and res.schema_errors == 1


def test_a_model_that_never_submits_stops(snap: Snapshot) -> None:
    res = run("q", snap, ScriptedProvider([Turn("hmm", []), Turn("still thinking", [])]))
    assert res.stop == "no_answer" and res.answer is None


def test_step_limit(snap: Snapshot) -> None:
    loop = [Turn("", [ToolCall(f"c{i}", "query_timeline", {})]) for i in range(5)]
    assert run("q", snap, ScriptedProvider(loop), max_steps=3).stop == "max_steps"


def test_without_runbook_nothing_of_it_is_reachable(snap: Snapshot) -> None:
    names = {s.name for s in tool_specs(use_runbook=False)}
    assert "search_runbook" not in names and "get_runbook_entry" not in names
    ev = _restart(snap)
    model = ScriptedProvider(
        [Turn("", [ToolCall("c", "get_event", {"event_id": ev})]), _submit(**good_answer(ev))]
    )
    res = run("q", snap, model, use_runbook=False)
    assert json.loads(model.seen[1][1][-1]["results"][0][1])["runbook"] == []
    assert "no runbook" in model.seen[0][0]
    assert res.validation is not None and res.validation.hallucinated_citations == 1  # RB-005
    assert snap.runbook.entries, "the caller's snapshot keeps its runbook"


def test_provider_message_formats() -> None:
    t = Turn("thinking", [ToolCall("id1", "get_event", {"event_id": "EV-000001"})])
    msgs = [
        {"role": "user", "text": "q"},
        {"role": "assistant", "turn": t},
        {"role": "tool", "results": [("id1", "{}")]},
    ]
    a = [AnthropicProvider._msg(m) for m in msgs]
    assert a[1]["content"][1] == {
        "type": "tool_use",
        "id": "id1",
        "name": "get_event",
        "input": {"event_id": "EV-000001"},
    }
    assert a[2] == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "id1", "content": "{}"}],
    }
    o = OpenAICompatProvider._msgs(msgs)
    assert o[1]["tool_calls"][0]["function"] == {
        "name": "get_event",
        "arguments": '{"event_id": "EV-000001"}',
    }
    assert o[2] == {"role": "tool", "tool_call_id": "id1", "content": "{}"}


def test_anthropic_adapter_parses_a_response() -> None:
    from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

    class Fake:
        class messages:
            @staticmethod
            def create(**kw: object) -> Message:
                tool = ToolUseBlock(
                    type="tool_use", id="t1", name="query_timeline", input={"limit": 5}
                )
                return Message(
                    id="m",
                    type="message",
                    role="assistant",
                    model="x",
                    stop_reason="tool_use",
                    content=[TextBlock(type="text", text="ok"), tool],
                    usage=Usage(input_tokens=10, output_tokens=3),
                )

    turn = AnthropicProvider(client=Fake()).complete("s", [{"role": "user", "text": "q"}], [])
    assert turn.text == "ok" and turn.calls == [ToolCall("t1", "query_timeline", {"limit": 5})]
    assert turn.usage == {"input_tokens": 10, "output_tokens": 3}
