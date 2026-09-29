"""Detector rules on synthetic captures: learn from a clean one, detect in a faulted one."""

import json
import math
import random
from pathlib import Path

import pytest

from shiftassist.detect.profile import learn
from shiftassist.detect.rules import detect

T0 = 1_790_620_000.0
N_MOD = 10


def iso(t: float) -> str:
    from datetime import UTC, datetime

    d = datetime.fromtimestamp(t, UTC)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def make_capture(
    root: Path,
    seed: int,
    *,
    duration: int = 1200,
    drift: tuple[int, float, float, float] | None = None,  # module, start s, end s, °C/h
    dead: tuple[int, float, float] | None = None,  # module, start s, end s
    camera_wide: float = 0.0,  # °C/h added to every module (shared warming)
    journal: list[dict[str, object]] | None = None,
    frozen: tuple[float, float] | None = None,  # gatherer frozen: queued, written at resume
    stopped: tuple[float, float] | None = None,  # gatherer stopped: messages lost
) -> str:
    rng = random.Random(seed)
    offsets = [rng.gauss(0, 0.6) for _ in range(N_MOD)]
    (root / "data" / "logs").mkdir(parents=True)
    records: list[dict[str, object]] = []

    def emit(t: float, rec: dict[str, object]) -> None:
        if stopped and stopped[0] <= t - T0 < stopped[1]:
            return
        w = t + 0.005
        if frozen and frozen[0] <= t - T0 < frozen[1]:
            w = T0 + frozen[1] + 0.001 * len(records) % 0.5
        records.append({"subsystem": rec.pop("subsystem"), "gathered_at": iso(w), **rec})

    with (root / "monitoring.jsonl").open("w") as fh:
        for s in range(duration):
            t = T0 + s
            emit(
                t,
                {
                    "subsystem": "chiller",
                    "timestamp": iso(t),
                    "supply_temperature": 23 + rng.gauss(0, 0.3),
                },
            )
            ambient = 0.4 * math.sin(2 * math.pi * s / 10800) + camera_wide * s / 3600
            for m in range(N_MOD):
                if dead and m == dead[0] and dead[1] <= s < dead[2]:
                    continue
                v = 24 + offsets[m] + ambient + rng.gauss(0, 0.03)
                if drift and m == drift[0] and s >= drift[1]:
                    v += drift[3] * (min(s, drift[2]) - drift[1]) / 3600
                emit(
                    t + 0.01 * m,
                    {
                        "subsystem": "slowsignal",
                        "timestamp": iso(t + 0.01 * m),
                        "tm_slot": m,
                        "temperature_sipm1": v,
                    },
                )
        records.sort(key=lambda r: str(r["gathered_at"]))  # the file is in write order
        fh.writelines(json.dumps(r) + "\n" for r in records)
    (root / "journal.jsonl").write_text("".join(json.dumps(r) + "\n" for r in journal or []))
    (root / "labels.jsonl").write_text("")
    return str(root)


@pytest.fixture(scope="module")
def profile(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    return learn(make_capture(tmp_path_factory.mktemp("base"), seed=1))


def test_clean_capture_gives_no_events(tmp_path: Path, profile) -> None:  # type: ignore[no-untyped-def]
    assert detect(make_capture(tmp_path, seed=2), profile) == []


def test_module_drift_is_localised(tmp_path: Path, profile) -> None:  # type: ignore[no-untyped-def]
    ev = detect(make_capture(tmp_path, seed=3, drift=(3, 400, 900, 12.0)), profile)
    trends = [e for e in ev if e.kind == "trend"]
    assert trends and {e.entity for e in trends} == {"tm03"}
    assert T0 + 400 <= trends[0].ts.timestamp() <= T0 + 400 + 240, "detected within ~4 min"


def test_dead_module_is_a_gap_and_does_not_fake_trends(tmp_path: Path, profile) -> None:  # type: ignore[no-untyped-def]
    """Regression: with raw values, a module dropping out shifted the cross-module median and
    produced false trends on every other module (P-14)."""
    ev = detect(make_capture(tmp_path, seed=4, dead=(7, 300, 420)), profile)
    gaps = [e for e in ev if e.kind == "gap"]
    assert [(e.subsystem, e.entity) for e in gaps] == [("slowsignal", "tm07")]
    assert 110 <= gaps[0].evidence["silence_s"] <= 125
    assert not [e for e in ev if e.kind == "trend"]


def test_camera_wide_change_is_one_event(tmp_path: Path, profile) -> None:  # type: ignore[no-untyped-def]
    """Every module warming together is not N module faults; it cancels in the residuals."""
    ev = detect(make_capture(tmp_path, seed=5, camera_wide=30.0), profile)
    assert len([e for e in ev if e.kind == "trend" and e.entity]) == 0


def _unit(t: float, unit: str, msg: str, **extra: object) -> dict[str, object]:
    return {
        "__REALTIME_TIMESTAMP": str(int((T0 + t) * 1e6)),
        "SYSLOG_IDENTIFIER": "systemd",
        "USER_UNIT": unit,
        "MESSAGE": msg,
        **extra,
    }


def test_crash_loop_is_one_restart_event(tmp_path: Path, profile) -> None:  # type: ignore[no-untyped-def]
    u = "sstcam-slowsignal.service"
    j = [_unit(5, u, "Started SSTCam Slowsignal Server.")]  # boot start: not a restart
    for k in range(4):
        t = 300 + 10 * k
        j += [
            _unit(
                t,
                u,
                f"{u}: Main process exited, code=exited, status=1/FAILURE",
                EXIT_CODE="exited",
                EXIT_STATUS="1",
            ),
            _unit(t + 1, u, f"{u}: Scheduled restart job, restart counter is at {k + 1}."),
            _unit(t + 2, u, "Started SSTCam Slowsignal Server."),
        ]
    ev = detect(make_capture(tmp_path, seed=6, journal=j), profile)
    (r,) = [e for e in ev if e.kind == "restart"]
    assert r.subsystem == "slowsignal" and r.severity == "alarm"
    assert r.evidence["restarts"] == 4 and "crash loop" in r.summary


def test_frozen_gatherer_is_one_stall_not_source_gaps(tmp_path: Path, profile) -> None:  # type: ignore[no-untyped-def]
    """R20: a frozen gatherer loses nothing; its write stream stops and the backlog is late."""
    ev = detect(make_capture(tmp_path, seed=7, frozen=(300, 360)), profile)
    assert [(e.kind, e.subsystem, e.rule_id) for e in ev] == [("gap", "gatherer", "R-STALL-01")]
    (e,) = ev
    assert 59 <= e.evidence["silence_s"] <= 61
    per = e.evidence["delayed_per_source"]
    assert per.keys() == {"chiller", "slowsignal"}  # every source held back, not one
    assert 55 <= per["chiller"] <= 60 and 550 <= per["slowsignal"] <= 600  # all but the last s
    assert T0 + 299 <= e.ts.timestamp() <= T0 + 300


def test_stopped_gatherer_is_source_gaps_not_a_stall(tmp_path: Path, profile) -> None:  # type: ignore[no-untyped-def]
    """Messages lost, nothing late: the sources' gaps are the evidence, not a stall."""
    ev = detect(make_capture(tmp_path, seed=8, stopped=(300, 360)), profile)
    assert not [e for e in ev if e.rule_id == "R-STALL-01"]
    assert {(e.kind, e.subsystem) for e in ev} == {("gap", "chiller"), ("gap", "slowsignal")}


def test_capture_without_receive_times_gives_no_stall_verdict(tmp_path: Path, profile) -> None:  # type: ignore[no-untyped-def]
    cap = make_capture(tmp_path, seed=9, frozen=(300, 360))
    f = Path(cap) / "monitoring.jsonl"
    rows = [json.loads(x) for x in f.read_text().splitlines()]
    f.write_text(
        "".join(json.dumps({k: v for k, v in r.items() if k != "gathered_at"}) + "\n" for r in rows)
    )
    assert not [e for e in detect(cap, profile) if e.rule_id == "R-STALL-01"]
