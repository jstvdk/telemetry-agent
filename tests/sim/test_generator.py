"""Scenario generator tests: determinism, stream invariants, and each fault's effect + label."""

import json
from datetime import timedelta
from pathlib import Path

import pytest

from shiftassist.sim.generator import SimResult, generate, write
from shiftassist.sim.records import LogRecord, TelemetryRecord
from shiftassist.sim.timeutil import iso, parse_iso
from tests.conftest import SCENARIOS, SimCache, scenario

MIN = 60_000


def logs(r: SimResult, **match: str) -> list[LogRecord]:
    return [
        x
        for x in r.records
        if isinstance(x, LogRecord) and all(getattr(x, k) == v for k, v in match.items())
    ]


def series(r: SimResult, camera: str, channel: str) -> list[TelemetryRecord]:
    return [
        x
        for x in r.records
        if isinstance(x, TelemetryRecord) and x.camera == camera and x.channel == channel
    ]


def t_ms(r: SimResult, ts: str) -> int:
    return round((parse_iso(ts) - r.scenario.start).total_seconds() * 1000)


# --- determinism (T-SC-SEED) ------------------------------------------------------------------


def test_same_seed_is_byte_identical(tmp_path: Path) -> None:
    sc = scenario("S03")
    write(generate(sc), tmp_path / "a")
    write(generate(sc), tmp_path / "b")
    for name in ("stream.jsonl", "labels.jsonl", "manifest.json"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_different_seed_differs() -> None:
    sc = scenario("S01")
    assert generate(sc, seed=1).records != generate(sc, seed=2).records


# --- stream invariants, every scenario -----------------------------------------------------


@pytest.mark.parametrize("path", SCENARIOS, ids=lambda p: p.stem)
def test_stream_invariants(path: Path, sim: type[SimCache]) -> None:
    r = sim.get(path.name.split("-")[0])
    times = [x.t_ms for x in r.records]
    assert times == sorted(times), "records must be in time order"
    assert times[0] >= 0 and times[-1] < r.scenario.duration_ms
    assert {x.camera for x in r.records} == set(r.scenario.cameras)
    start, end = r.scenario.start, r.scenario.start + timedelta(milliseconds=r.scenario.duration_ms)
    for lb in r.labels:
        assert lb.label_id.startswith(r.scenario.id + "-L")
        for ev in lb.expected_events:
            assert start <= parse_iso(ev.near) < end
    # every fault produced at least one label per affected camera
    for i, f in enumerate(r.scenario.faults):
        cams = f.cameras or r.scenario.cameras
        assert {lb.camera for lb in r.labels if lb.fault_index == i} == set(cams)


def test_serialised_timestamps_are_utc_millis(tmp_path: Path) -> None:
    write(generate(scenario("S05")), tmp_path)
    first = json.loads((tmp_path / "stream.jsonl").open().readline())
    assert first["ts"].endswith("Z") and len(first["ts"]) == len("2026-10-14T22:00:00.000Z")


# --- nominal behaviour and v0 traps --------------------------------------------------------


@pytest.mark.parametrize("sid", ["S01", "S08"])
def test_healthy_nights_have_no_errors_but_do_have_traps(sid: str, sim: type[SimCache]) -> None:
    r = sim.get(sid)
    assert r.labels == []
    levels = {x.level for x in logs(r)}
    assert levels <= {"DEBUG", "INFO", "WARNING"}
    # the lines that fooled v0's substring counter (finding F1) must be present
    texts = [x.text for x in logs(r)]
    assert any("error_count=0" in t for t in texts)
    assert any("NO_ERROR" in t for t in texts)
    assert sum("ERROR" in t.upper() for t in texts) > 50


def test_nominal_telemetry_within_limits(sim: type[SimCache]) -> None:
    r = sim.get("S01")
    assert max(x.value for x in series(r, "cam-01", "hv.current_ua")) < 100
    temps = [x.value for x in series(r, "cam-01", "cooling.plate_temp_c")]
    assert min(temps) > 14.5 and max(temps) < 15.5


def test_noise_settings_raise_benign_warnings(sim: type[SimCache]) -> None:
    per_hour = {
        sid: len(logs(sim.get(sid), level="WARNING"))
        / (sim.get(sid).scenario.duration_ms / 3_600_000)
        for sid in ("S01", "S08")
    }
    assert per_hour["S08"] > 3 * per_hour["S01"]


# --- faults --------------------------------------------------------------------------------


def test_cooling_drift_slope(sim: type[SimCache]) -> None:
    r = sim.get("S02")
    (lb,) = r.labels
    t0 = t_ms(r, lb.start)
    pts = [
        (x.t_ms / 3_600_000, x.value)
        for x in series(r, "cam-01", "cooling.plate_temp_c")
        if x.t_ms >= t0
    ]
    n = len(pts)
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    slope = sum((x - mx) * (y - my) for x, y in pts) / sum((x - mx) ** 2 for x, _ in pts)
    assert slope == pytest.approx(0.8, abs=0.05)
    assert lb.expected_events[0].kind == "trend"
    assert lb.expected_events[0].channel == "cooling.plate_temp_c"


def test_readout_crash_chain(sim: type[SimCache]) -> None:
    r = sim.get("S03")
    crash = next(lb for lb in r.labels if lb.kind == "readout_crash")
    kinds = [e.kind for e in crash.expected_events]
    assert kinds == ["config_change", "traceback", "restart"]
    assert crash.start.startswith("2026-10-15T01:50") and crash.details["crash_at"].startswith(
        "2026-10-15T02:13"
    )

    cfg = [x for x in logs(r, subsystem="config") if "reloaded" in x.text]
    assert len(cfg) == 1 and "buffer_size=4096" in cfg[0].text
    (tb,) = [x for x in logs(r, level="ERROR") if "Traceback" in x.text]
    assert "BufferSizeMismatch" in tb.text and "\n" in tb.text
    assert iso(r.scenario.start, tb.t_ms) == crash.details["crash_at"]

    t_crash, t_restart = t_ms(r, crash.details["crash_at"]), t_ms(r, crash.details["restart_at"])
    down = [
        x for x in series(r, "cam-01", "readout.trigger_rate_hz") if t_crash <= x.t_ms < t_restart
    ]
    assert down and all(x.value == 0.0 for x in down)
    hb = [
        x
        for x in logs(r, subsystem="readout")
        if "heartbeat" in x.text and t_crash <= x.t_ms < t_restart
    ]
    assert hb == []


def test_distractor_is_labelled_and_harmless(sim: type[SimCache]) -> None:
    r = sim.get("S03")
    (d,) = [lb for lb in r.labels if lb.kind == "distractor"]
    assert d.expected_events == []
    temps = [x.value for x in series(r, "cam-01", "cooling.plate_temp_c")]
    assert max(temps) < 16.0  # visible bump, far below any alarm limit


def test_hv_trips(sim: type[SimCache]) -> None:
    r = sim.get("S04")
    trips = [lb for lb in r.labels if lb.kind == "hv_trip"]
    assert len(trips) == 2
    assert len([x for x in logs(r, level="ERROR") if "HV trip" in x.text]) == 2
    cur = series(r, "cam-01", "hv.current_ua")
    volt = series(r, "cam-01", "hv.voltage_v")
    for lb in trips:
        t_trip = t_ms(r, lb.details["trip_at"])
        before = [x.value for x in cur if t_trip - 20_000 <= x.t_ms < t_trip]
        assert max(before) > 150.0, "telemetry must actually cross the limit"
        assert all(x.value == 0.0 for x in volt if t_trip <= x.t_ms < t_trip + 5 * MIN)
        assert volt[-1].value > 1000  # recovered


def test_network_drop_is_a_real_gap(sim: type[SimCache]) -> None:
    r = sim.get("S05")
    (lb,) = r.labels
    t0, t1 = t_ms(r, lb.start), t_ms(r, lb.end)
    inside = [x for x in r.records if t0 <= x.t_ms < t1]
    assert inside == [], "no logs or telemetry while the link is down"
    after = [x for x in logs(r, subsystem="os") if "was down" in x.text]
    assert len(after) == 1 and after[0].t_ms >= t1


def test_common_cause_within_jitter(sim: type[SimCache]) -> None:
    r = sim.get("S09")
    starts = sorted(t_ms(r, lb.start) for lb in r.labels)
    assert len(starts) == 3 and len({lb.group for lb in r.labels}) == 1
    assert starts[-1] - starts[0] <= 20_000
    assert len(set(starts)) > 1, "jitter should spread the cameras"


def test_disk_full_chain(sim: type[SimCache]) -> None:
    r = sim.get("S06")
    (lb,) = r.labels
    disk = series(r, "cam-01", "os.disk_used_pct")
    assert max(x.value for x in disk) == 100.0
    assert disk[-1].value < 70
    t_full, t_purge = t_ms(r, lb.details["full_at"]), t_ms(r, lb.details["purged_at"])
    rate = [x.value for x in series(r, "cam-01", "daq.event_rate_hz") if t_full <= x.t_ms < t_purge]
    assert rate and set(rate) == {0.0}
    enospc = [x for x in logs(r, subsystem="daq", level="ERROR") if "Errno 28" in x.text]
    assert len(enospc) >= 10


def test_new_signature_repeats(sim: type[SimCache]) -> None:
    r = sim.get("S07")
    (lb,) = r.labels
    hits = [x for x in logs(r, level="ERROR") if x.text == lb.details["text"]]
    assert len(hits) == lb.details["repeats"] == 3


def test_prompt_injection_line_present(sim: type[SimCache]) -> None:
    r = sim.get("S10")
    kinds = sorted(lb.kind for lb in r.labels)
    assert kinds == ["hv_trip", "prompt_injection"]
    assert any("IGNORE ALL PREVIOUS INSTRUCTIONS" in x.text for x in logs(r, subsystem="daq"))
