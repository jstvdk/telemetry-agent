"""Label-evidence checks on a tiny synthetic capture: found, not found, inconclusive."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from shiftassist.collect.evidence import render, shift_label, verify
from shiftassist.sim.records import ExpectedEvent, Label
from shiftassist.sim.timeutil import iso

T0 = datetime(2026, 9, 28, 20, 0, 0, tzinfo=UTC)


def at(s: float) -> str:
    return iso(T0, round(s * 1000))


def write_capture(
    root: Path,
    labels: list[Label],
    silent: tuple[float, float] | None = None,
    drift_from: float | None = None,
    frozen: tuple[float, float] | None = None,
) -> Path:
    """600 s of 1 Hz chiller monitoring with receive times; optional silence (messages lost),
    gatherer freeze (messages written late, at the end of the freeze) and a temperature ramp."""
    (root / "data" / "logs").mkdir(parents=True)
    with (root / "monitoring.jsonl").open("w") as fh:
        for s in range(600):
            if silent and silent[0] <= s < silent[1]:
                continue
            temp = 23.0 + (
                0.01 * (s - drift_from) if drift_from is not None and s >= drift_from else 0
            )
            temp += 0.02 * ((s * 7919) % 11 - 5) / 5  # deterministic small noise
            w = frozen[1] if frozen and frozen[0] <= s < frozen[1] else s + 0.005
            rec = {"subsystem": "chiller", "gathered_at": at(w), "timestamp": at(s)}
            fh.write(json.dumps({**rec, "supply_temperature": temp}) + "\n")
    (root / "journal.jsonl").write_text("")
    (root / "labels.jsonl").write_text("".join(lb.model_dump_json() + "\n" for lb in labels))
    return root


def label(kind: str, start: float, end: float, ev: ExpectedEvent) -> Label:
    return Label(
        label_id="T-L01",
        scenario="T",
        fault_index=0,
        group="T-F00",
        kind=kind,
        camera="cam-x",
        subsystem=ev.subsystem,
        start=at(start),
        end=at(end),
        root_cause="",
        expected_events=[ev],
    )


GAP = ExpectedEvent(kind="gap", camera="cam-x", subsystem="chiller", near=at(200), tolerance_s=30)
TREND = ExpectedEvent(
    kind="trend",
    camera="cam-x",
    subsystem="chiller",
    near=at(400),
    tolerance_s=60,
    channel="supply_temperature",
)


def test_gap_found_only_when_silent(tmp_path: Path) -> None:
    lb = label("process_hang", 200, 290, GAP)
    (c,) = verify(write_capture(tmp_path / "a", [lb], silent=(200, 290)))
    assert c.found is True and "91.0 s" in c.detail  # last message at 199 s, next at 290 s
    (c,) = verify(write_capture(tmp_path / "b", [lb]))
    assert c.found is False


def test_gatherer_stall_needs_silence_and_a_late_backlog(tmp_path: Path) -> None:
    ev = GAP.model_copy(update={"subsystem": "gatherer"})
    lb = label("process_hang", 200, 260, ev)
    (c,) = verify(write_capture(tmp_path / "frozen", [lb], frozen=(200, 260)))
    assert c.found is True and "59 messages" in c.detail, c.detail  # the last is 1 s late
    (c,) = verify(write_capture(tmp_path / "lost", [lb], silent=(200, 260)))
    assert c.found is False, "silence without a late backlog is data lost, not a stall"
    (c,) = verify(write_capture(tmp_path / "clean", [lb]))
    assert c.found is False


def test_trend_found_only_with_drift(tmp_path: Path) -> None:
    lb = label("chiller_ramp", 300, 500, TREND)
    (c,) = verify(write_capture(tmp_path / "a", [lb], drift_from=300))
    assert c.found is True, c.detail
    (c,) = verify(write_capture(tmp_path / "b", [lb]))
    assert c.found is False, c.detail


def test_window_outside_capture_is_inconclusive(tmp_path: Path) -> None:
    lb = label("process_hang", 580, 700, GAP.model_copy(update={"near": at(580)}))
    (c,) = verify(write_capture(tmp_path, [lb]))
    assert c.found is None and "inconclusive" in c.detail
    assert "0/0" in render([c]) and "1 inconclusive" in render([c])


def test_shift_label_moves_every_timestamp() -> None:
    lb = label("process_hang", 200, 290, GAP)
    moved = shift_label(lb, 3600)
    assert moved.start == at(3800) and moved.end == at(3890)
    assert moved.expected_events[0].near == at(3800)
    assert lb.start == at(200), "original unchanged"
    assert timedelta(seconds=3600) == (
        datetime.fromisoformat(moved.start.replace("Z", "+00:00"))
        - datetime.fromisoformat(lb.start.replace("Z", "+00:00"))
    )
