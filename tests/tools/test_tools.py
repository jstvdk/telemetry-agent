"""Tools on a small synthetic snapshot: the schema contract, windows, drill-down, errors, caps."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shiftassist.detect.profile import learn
from shiftassist.detect.rules import detect
from shiftassist.tools import REGISTRY, Snapshot, anthropic_tools, openai_tools
from shiftassist.tools.registry import cap_output
from tests.detect.test_rules import T0, _unit, make_capture

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def snap(tmp_path_factory: pytest.TempPathFactory) -> Snapshot:
    base = make_capture(tmp_path_factory.mktemp("base"), seed=1)
    prof = learn(base)
    u = "sstcam-slowsignal.service"
    journal = [_unit(5, u, "Started SSTCam Slowsignal Server.")]
    journal += [
        _unit(
            300,
            u,
            f"{u}: Main process exited, code=exited, status=1/FAILURE",
            EXIT_CODE="exited",
            EXIT_STATUS="1",
        ),
        _unit(301, u, "Started SSTCam Slowsignal Server."),
    ]
    cap = Path(
        make_capture(
            tmp_path_factory.mktemp("cap"), seed=3, drift=(3, 400, 900, 12.0), journal=journal
        )
    )
    events = detect(str(cap), prof)
    (cap / "events.jsonl").write_text("".join(e.model_dump_json() + "\n" for e in events))
    p = cap / "profile.json"
    prof.save(p)
    return Snapshot(cap, profile=p, runbook=ROOT / "runbook")


def call(snap: Snapshot, name: str, **args: object) -> dict:  # type: ignore[type-arg]
    return json.loads(REGISTRY[name].call(snap, args))


def test_one_registry_both_formats() -> None:
    """ADR-0006: every tool described once; the snapshot is never a model-visible parameter."""
    a, o = anthropic_tools(), openai_tools()
    assert [t["name"] for t in a] == [t["function"]["name"] for t in o] == list(REGISTRY)
    for t in a:
        assert len(t["description"]) > 40, t["name"]
        assert "snap" not in t["input_schema"].get("properties", {})
    assert all(t.read_only for t in REGISTRY.values())


def test_timeline_window_and_filters(snap: Snapshot) -> None:
    everything = call(snap, "query_timeline")
    assert everything["total"] == len(snap.events) >= 2
    kinds = {e["kind"] for e in everything["events"]}
    assert {"restart", "trend"} <= kinds
    only = call(snap, "query_timeline", kind="restart")
    assert [e["kind"] for e in only["events"]] == ["restart"]
    early = call(snap, "query_timeline", end=snap.start.isoformat(), since_minutes=1)
    assert early["total"] == 0


def test_event_drill_down_resolves_raw_lines_and_runbook(snap: Snapshot) -> None:
    rst = call(snap, "query_timeline", kind="restart")["events"][0]
    ev = call(snap, "get_event", event_id=rst["id"])
    assert ev["raw"] and "status=1/FAILURE" in ev["raw"][0]["text"]
    assert "RB-005" in {r["id"] for r in ev["runbook"]}


def test_unit_history_says_what_happened(snap: Snapshot) -> None:
    h = call(snap, "get_unit_history", unit="slowsignal")
    events = [i["event"] for i in h["items"]]
    assert "exited" in events and events.count("started") == 2
    assert call(snap, "get_unit_history", unit="nosuch")["error"].startswith("unknown unit")


def test_telemetry_features_see_the_drift_relative_to_other_modules(snap: Snapshot) -> None:
    f = call(
        snap,
        "get_telemetry_features",
        subsystem="slowsignal",
        channel="temperature_sipm1",
        entity="tm03",
        since_minutes=8,
        end=datetime.fromtimestamp(T0 + 900, UTC).isoformat(),
    )
    assert f["n"] > 400 and f["longest_silence_s"] <= 1.5
    assert 10 < f["relative_slope_per_h"] < 14  # 12 °C/h injected
    assert f["baseline"]["on_relative_slope"] is True
    err = call(
        snap, "get_telemetry_features", subsystem="slowsignal", channel="nope", entity="tm03"
    )
    assert "temperature_sipm1" in err["error"]


def test_output_is_capped_with_a_flag() -> None:
    out = json.loads(cap_output({"items": list(range(5000)), "total": 5000}, 500))
    assert out["truncated"] is True and 0 < len(out["items"]) < 5000 and out["total"] == 5000


def test_bad_arguments_come_back_as_readable_errors(snap: Snapshot) -> None:
    out = call(snap, "query_timeline", limit=0)
    assert out["error"] == "invalid arguments"
