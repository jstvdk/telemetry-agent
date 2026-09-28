import pytest
from pydantic import ValidationError

from shiftassist.sim.scenario import Scenario, load_scenario
from shiftassist.sim.timeutil import iso, parse_duration_ms
from tests.conftest import SCENARIOS

BASE = {"id": "T", "title": "t", "seed": 1, "start": "2026-10-14T22:00:00Z", "duration": "1h"}


@pytest.mark.parametrize(
    ("text", "ms"),
    [
        ("3h50m", 13_800_000),
        ("23m", 1_380_000),
        ("40s", 40_000),
        ("1h", 3_600_000),
        ("0s", 0),
        ("1.5s", 1500),
    ],
)
def test_parse_duration(text: str, ms: int) -> None:
    assert parse_duration_ms(text) == ms


@pytest.mark.parametrize("text", ["", "5", "3x", "m", "1h 2m"])
def test_parse_duration_rejects(text: str) -> None:
    with pytest.raises(ValueError):
        parse_duration_ms(text)


def test_iso_is_utc_with_millis() -> None:
    sc = Scenario.model_validate(BASE)
    assert iso(sc.start, 3 * 3_600_000 + 50 * 60_000 + 7) == "2026-10-15T01:50:00.007Z"


@pytest.mark.parametrize("path", SCENARIOS, ids=lambda p: p.stem)
def test_shipped_scenarios_load(path: object) -> None:
    sc = load_scenario(path)  # type: ignore[arg-type]
    assert sc.id == path.name.split("-")[0]  # type: ignore[attr-defined]


def test_scenario_set_is_complete() -> None:
    assert [p.name.split("-")[0] for p in SCENARIOS] == [f"S{i:02d}" for i in range(1, 11)]


def test_unknown_fault_kind_rejected() -> None:
    with pytest.raises(ValidationError, match="kind"):
        Scenario.model_validate({**BASE, "faults": [{"kind": "meteor_strike", "at": "5m"}]})


def test_misspelled_fault_parameter_rejected() -> None:
    with pytest.raises(ValidationError, match="slope"):
        Scenario.model_validate(
            {**BASE, "faults": [{"kind": "cooling_drift", "at": "5m", "slope_c_per_hr": 1}]}
        )


def test_fault_outside_duration_rejected() -> None:
    with pytest.raises(ValidationError, match="outside duration"):
        Scenario.model_validate({**BASE, "faults": [{"kind": "hv_trip", "at": "2h"}]})


def test_fault_on_unknown_camera_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown cameras"):
        Scenario.model_validate(
            {**BASE, "faults": [{"kind": "hv_trip", "at": "5m", "cameras": ["cam-99"]}]}
        )


def test_naive_start_time_rejected() -> None:
    with pytest.raises(ValidationError):
        Scenario.model_validate({**BASE, "start": "2026-10-14T22:00:00"})
