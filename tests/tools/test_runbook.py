"""The runbook as data: every entry parses, and retrieval by event works on real detector events."""

from pathlib import Path

import pytest
import yaml

from shiftassist.detect.model import Event
from shiftassist.tools.runbook import Runbook

ROOT = Path(__file__).resolve().parents[2]
RB = Runbook.load(ROOT / "runbook")
EVENTS = [
    Event.model_validate_json(x)
    for f in sorted((ROOT / "tests/fixtures/events").glob("*.jsonl"))
    for x in f.read_text().splitlines()
    if x.strip()
]


def test_every_entry_is_well_formed() -> None:
    assert len(RB.entries) >= 11
    for e in RB.entries.values():
        assert e.path.startswith(e.id)
        assert e.status in ("ai-draft", "verified", "obsolete")
        assert e.matches, f"{e.id}: no matches block; it can only be found by search"
        assert all(isinstance(s, str) for s in e.sources), f"{e.id}: a source parsed as non-text"
        for need in ("Symptom", "Checks", "Fix / mitigation", "Escalation"):
            assert need in e.sections, f"{e.id}: missing section {need}"
        if e.status == "verified":
            assert e.front.get("verified_by") and e.front.get("verified_on"), e.id


def test_index_lists_every_entry() -> None:
    index = (ROOT / "runbook/README.md").read_text()
    for e in RB.entries.values():
        assert f"({e.path})" in index, f"{e.id} missing from runbook/README.md"


def test_every_real_detector_event_finds_an_entry() -> None:
    """X-18a: a guessed pattern made an entry unreachable. Every B01/B02 event must retrieve one."""
    assert len(EVENTS) >= 40
    missing = [(e.event_id, e.kind, e.subsystem, e.rule_id) for e in EVENTS if not RB.for_event(e)]
    assert not missing


def _ids(ev: Event) -> set[str]:
    return {e.id for e, _ in RB.for_event(ev)}


@pytest.mark.parametrize(
    ("pick", "want", "not_want"),
    [
        (lambda e: e.rule_id == "R-STALL-01", {"RB-003"}, {"RB-001", "RB-002"}),
        (lambda e: e.kind == "gap" and e.entity, {"RB-004"}, {"RB-001", "RB-002", "RB-011"}),
        (lambda e: e.kind == "restart" and e.subsystem == "pointing", {"RB-005", "RB-006"}, set()),
        (lambda e: e.kind == "traceback", {"RB-005"}, set()),
        (lambda e: e.kind == "log_burst", {"RB-007"}, set()),
        (lambda e: e.kind == "trend" and e.entity, {"RB-008"}, {"RB-009"}),
        (lambda e: e.kind == "trend" and e.subsystem == "chiller", {"RB-009"}, {"RB-008"}),
    ],
)
def test_retrieval_by_event(pick, want, not_want) -> None:  # type: ignore[no-untyped-def]
    evs = [e for e in EVENTS if pick(e)]
    assert evs
    for ev in evs:
        assert want <= _ids(ev) and not (not_want & _ids(ev)), (ev.event_id, _ids(ev))


def test_multi_event_conditions_are_reported_not_hidden() -> None:
    """RB-002 fits a subsystem gap only if every subsystem went silent: said in applies_if."""
    gap = next(e for e in EVENTS if e.kind == "gap" and e.subsystem == "chiller")
    cond = dict((e.id, c) for e, c in RB.for_event(gap))
    assert cond["RB-001"] == {} and cond["RB-002"] == {"simultaneous": "all"}


def test_search_ranks_the_obvious_entry_first() -> None:
    for query, want in [
        ("pointing keeps restarting", "RB-006"),
        ("FileNotFoundError calibration crash loop", "RB-005"),
        ("Hardware error detected warnings", "RB-007"),
        ("gatherer late backlog", "RB-003"),
        ("chiller setpoint supply temperature rising", "RB-009"),
    ]:
        assert RB.search(query, 1)[0][0].id == want, query


def test_front_matter_is_plain_yaml() -> None:
    for p in (ROOT / "runbook").glob("RB-*.md"):
        yaml.safe_load(p.read_text().split("---")[1])
