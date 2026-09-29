"""Scorer: one event is credited to at most one expected event (X-15b)."""

from datetime import UTC, datetime, timedelta

from shiftassist.detect.model import Event
from shiftassist.detect.score import score
from shiftassist.sim.records import ExpectedEvent, Label

T0 = datetime(2026, 9, 28, 23, 0, tzinfo=UTC)


def iso(s: float) -> str:
    return (T0 + timedelta(seconds=s)).isoformat().replace("+00:00", "Z")


def label(lid: str, start: float, end: float, *exp: tuple[str, str, str | None]) -> Label:
    return Label(
        label_id=lid,
        scenario="T",
        fault_index=0,
        group=lid,
        kind="k",
        camera="cam-01",
        subsystem=exp[0][1],
        start=iso(start),
        end=iso(end),
        root_cause="",
        expected_events=[
            ExpectedEvent(
                kind=k, camera="cam-01", subsystem=s, near=iso(start), tolerance_s=30, entity=ent
            )  # type: ignore[arg-type]
            for k, s, ent in exp
        ],
    )


def event(eid: str, t: float, kind: str, sub: str, entity: str | None = None) -> Event:
    return Event(
        event_id=eid,
        ts=T0 + timedelta(seconds=t),
        camera="cam-01",
        subsystem=sub,
        entity=entity,
        kind=kind,  # type: ignore[arg-type]
        severity="warning",
        rule_id="R",
        summary="",
    )


def test_one_event_cannot_explain_two_overlapping_faults() -> None:
    """The B02 case: two faults 6 s apart both expect a slow-signal gap; there is one gap."""
    labels = [
        label("L08", 0, 60, ("gap", "slowsignal", None)),
        label("L09", 6, 70, ("gap", "slowsignal", None)),
    ]
    s = score("t", [event("EV-1", 10, "gap", "slowsignal")], labels, 1.0)
    assert sum(r.how is not None for r in s.expected) == 1
    assert s.recall == 0.5
    assert [e.event_id for e in s.tp] == ["EV-1"]


def test_matching_is_maximal_not_greedy() -> None:
    labels = [
        label("L1", 0, 60, ("trend", "slowsignal", "tm07")),  # window -30 … 90 s
        label("L2", 80, 100, ("trend", "slowsignal", "tm07")),  # window 50 … 130 s
    ]
    # L1 prefers EV-1 (exact module), but EV-1 is L2's only candidate. Greedy: recall 1/2.
    evs = [
        event("EV-1", 60, "trend", "slowsignal", "tm07"),
        event("EV-2", 5, "trend", "slowsignal"),
    ]
    s = score("t", evs, labels, 1.0)
    assert s.recall == 1.0
    assert {r.label.label_id: (r.how, r.events) for r in s.expected} == {
        "L1": ("partial", ["EV-2"]),
        "L2": ("exact", ["EV-1"]),
    }


def test_exact_module_preferred_and_repeats_are_duplicates() -> None:
    labels = [label("L1", 0, 60, ("trend", "slowsignal", "tm07"))]
    evs = [
        event("EV-1", 5, "trend", "slowsignal"),  # no entity: partial
        event("EV-2", 20, "trend", "slowsignal", "tm07"),  # exact
        event("EV-3", 40, "trend", "slowsignal", "tm07"),  # same fault again
        event("EV-4", 900, "gap", "chiller"),  # nowhere near a fault
    ]
    s = score("t", evs, labels, 1.0)
    (r,) = s.expected
    assert (r.how, r.events) == ("exact", ["EV-2"])
    assert [e.event_id for e in s.duplicates] == ["EV-1", "EV-3"]
    assert [e.event_id for e in s.false_alarms] == ["EV-4"]
    assert s.precision_strict == 0.25 and s.precision_lenient == 0.75


def test_event_is_credited_to_the_fault_it_most_plausibly_belongs_to() -> None:
    """B02 L08/L09: the gap came 75 s into L08 but 8 s into L09; it is L09's gap."""
    labels = [
        label("L08", 0, 90, ("gap", "slowsignal", None)),
        label("L09", 67, 140, ("gap", "slowsignal", None)),
    ]
    s = score("t", [event("EV-16", 75, "gap", "slowsignal")], labels, 1.0)
    assert {r.label.label_id: r.events for r in s.expected} == {"L08": [], "L09": ["EV-16"]}


def test_assignment_is_optimal_against_brute_force() -> None:
    import itertools
    import random

    from shiftassist.detect.score import UNMATCHED, _assign

    rng = random.Random(0)
    for _ in range(300):
        n, m = rng.randint(1, 4), rng.randint(0, 4)
        cost = [[rng.choice([None, rng.randint(0, 50)]) for _ in range(m)] for _ in range(n)]

        def total(a: dict[int, int], cost: list[list[int | None]] = cost) -> float:
            return sum(UNMATCHED if i not in a else cost[i][a[i]] or 0 for i in range(len(cost)))

        best = UNMATCHED * n
        for cols in itertools.product([None, *range(m)], repeat=n):
            used = [j for j in cols if j is not None]
            if len(used) != len(set(used)) or any(
                j is not None and cost[i][j] is None for i, j in enumerate(cols)
            ):
                continue
            best = min(best, total({i: j for i, j in enumerate(cols) if j is not None}))
        got = _assign(cost)
        assert len(set(got.values())) == len(got)
        assert all(cost[i][j] is not None for i, j in got.items())
        assert total(got) == best, (cost, got)
