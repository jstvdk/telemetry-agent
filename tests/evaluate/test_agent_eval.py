"""Agent evaluation: questions from labels, expected runbook entries, scoring, the rule baseline."""

from datetime import UTC, datetime, timedelta

from shiftassist.evaluate.agent import evaluate, expected_entry, questions
from shiftassist.evaluate.baseline import BaselineProvider
from shiftassist.sim.records import ExpectedEvent, Label
from shiftassist.tools import Snapshot
from tests.detect.test_rules import T0
from tests.tools.test_tools import snap as snap  # fixture

MAP = {
    "process_crash": {"chiller": ["RB-001", "RB-005"], "default": "RB-005"},
    "brand_new_fault": "none",
    "slowsignal_drift": "RB-008",
}


def at(s: float) -> str:
    return (
        (datetime.fromtimestamp(T0, UTC) + timedelta(seconds=s)).isoformat().replace("+00:00", "Z")
    )


def label(
    lid: str, kind: str, start: float, end: float, unit: str | None = None, ev: str = "restart"
) -> Label:
    sub = unit or "slowsignal"
    expected = ExpectedEvent(kind=ev, camera="c", subsystem=sub, near=at(start), tolerance_s=30)  # type: ignore[arg-type]
    return Label(
        label_id=lid,
        scenario="T",
        fault_index=0,
        group=lid,
        kind=kind,
        camera="c",
        subsystem=sub,
        start=at(start),
        end=at(end),
        root_cause="",
        expected_events=[expected],
        details={"fault": {"unit": unit}} if unit else {},
    )


def test_expected_entry_by_kind_and_unit() -> None:
    assert expected_entry(label("a", "process_crash", 0, 1, "chiller"), MAP) == {"RB-001", "RB-005"}
    assert expected_entry(label("b", "process_crash", 0, 1, "target"), MAP) == {"RB-005"}
    assert expected_entry(label("c", "brand_new_fault", 0, 1), MAP) == set()


def test_questions_group_overlaps_and_do_not_leak_into_neighbours(snap: Snapshot) -> None:
    labels = [
        label("L1", "process_crash", 100, 160, "chiller"),
        label("L2", "process_crash", 120, 150, "target"),  # starts while L1 is active
        label("L3", "slowsignal_drift", 400, 900, ev="trend"),
    ]
    q1, q2 = questions(snap, labels, MAP)
    assert q1.qid == "L1+L2" and q1.expected_entries == {"RB-001", "RB-005"}
    assert q1.window[1] < datetime.fromtimestamp(T0 + 400, UTC), "stops before the next fault"
    assert q2.window[0] > datetime.fromtimestamp(T0 + 160, UTC)


def test_rule_baseline_end_to_end(snap: Snapshot) -> None:
    labels = [
        label("L1", "process_crash", 299, 305, "slowsignal"),
        label("L2", "slowsignal_drift", 400, 900, ev="trend"),
    ]
    rep = evaluate(snap, labels, MAP | {"process_crash": "RB-005"}, BaselineProvider, k=2)
    s = rep.summary()
    assert s["runs"] == 4 and s["submitted"] == 1.0 and s["hallucinated_citations"] == 0
    by_q = {r["qid"]: r for r in rep.rows}
    assert by_q["L1"]["runbook_ok"] and by_q["L1"]["evidence_recall"] == 1.0
    assert by_q["L2"]["runbook_entry"] == "RB-008" and by_q["L2"]["runbook_ok"]
    assert s["pass_k"] == 1.0


def test_unknown_fault_needs_not_in_runbook(snap: Snapshot) -> None:
    labels = [label("L1", "brand_new_fault", 299, 305, "slowsignal")]
    (row,) = evaluate(snap, labels, MAP, BaselineProvider).rows
    assert row["runbook_entry"] == "RB-005" and row["runbook_ok"] is False, (
        "a confident wrong entry"
    )
