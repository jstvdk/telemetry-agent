"""Harness tests against a fake container (no Docker): schedule, always-revert, labels, safety."""

import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from shiftassist.lab.box import Box
from shiftassist.lab.faults import DiskFull, Injected
from shiftassist.lab.harness import Scenario, load_scenario, run

LAB = Path(__file__).resolve().parents[2] / "lab" / "camera-in-a-box" / "scenarios"
T0 = 1_790_620_000.0


class FakeCamera:
    """Answers the docker-exec commands the harness sends; keeps a clock and a command log."""

    def __init__(self, fail_on: str | None = None, df: str = "tmpfs 1073741824 1000000000"):
        self.clock = T0
        self.cmds: list[str] = []
        self.fail_on = fail_on
        self.df = df
        self.unhealthy: set[str] = set()

    def __call__(self, argv: list[str], stdin: str | None) -> subprocess.CompletedProcess[str]:
        if argv[-2:] == ["date", "+%s.%N"]:
            return subprocess.CompletedProcess(argv, 0, f"{self.clock:.6f}\n", "")
        cmd = argv[-1]
        self.cmds.append(cmd)
        out, rc = "", 0
        if " show " in cmd:
            unit = cmd.split()[3]
            state = "failed" if any(u in unit for u in self.unhealthy) else "active"
            out = f"ActiveState={state}\nMainPID=4242\n"
        elif "df -B1" in cmd:
            out = self.df + "\n"
        if self.fail_on and self.fail_on in cmd:
            rc = 1
        return subprocess.CompletedProcess(argv, rc, out, "boom" if rc else "")


class FakeBox(Box):
    def sleep(self, seconds: float) -> None:
        assert self.runner is not None
        self.runner.clock += max(0.0, seconds)  # type: ignore[attr-defined]


def box(cam: FakeCamera) -> FakeBox:
    return FakeBox("cam-x", runner=cam)


def scenario(*faults: dict[str, object], settle: str = "1m") -> Scenario:
    return Scenario.model_validate(
        {"id": "T", "title": "t", "settle": settle, "cooldown": "10s", "faults": list(faults)}
    )


# --- scenario files ----------------------------------------------------------------------------


@pytest.mark.parametrize("path", sorted(LAB.glob("B*.yaml")), ids=lambda p: p.stem)
def test_shipped_scenarios_load(path: Path) -> None:
    assert load_scenario(path).id == path.name.split("-")[0]


def test_faults_must_be_in_time_order() -> None:
    with pytest.raises(ValidationError, match="time order"):
        scenario({"kind": "gatherer_down", "at": "5m"}, {"kind": "gatherer_down", "at": "2m"})


def test_first_fault_after_settle() -> None:
    with pytest.raises(ValidationError, match="settle"):
        scenario({"kind": "gatherer_down", "at": "30s"}, settle="1m")


def test_unknown_fault_rejected() -> None:
    with pytest.raises(ValidationError):
        scenario({"kind": "meteor", "at": "2m"})


# --- running -------------------------------------------------------------------------------------


def test_schedule_and_labels(tmp_path: Path) -> None:
    cam = FakeCamera()
    sc = scenario(
        {"kind": "process_crash", "at": "1m", "unit": "chiller", "hold": "2m"},
        {"kind": "module_dead", "at": "5m", "module": 5, "hold": "30s"},
    )
    res = run(sc, box(cam), tmp_path)
    assert res.aborted is None and len(res.labels) == 2
    crash, dead = res.labels
    assert crash.start == "2026-09-28T18:27:40.000Z"  # T0 (18:26:40) + 60 s, container clock
    assert crash.end == "2026-09-28T18:29:40.000Z"  # + 2 min hold
    assert [e.kind for e in crash.expected_events] == ["restart", "gap"]
    assert dead.expected_events[0].entity == "tm05"
    kill = next(c for c in cam.cmds if "kill -s SIGKILL" in c)
    assert "sstcam-chiller.service" in kill
    assert any("chiller connect" in c for c in cam.cmds), "chiller must be reconnected"
    lines = (tmp_path / "labels.jsonl").read_text().splitlines()
    assert [json.loads(x)["label_id"] for x in lines] == ["T-L01", "T-L02"]


def test_revert_runs_when_hold_fails(tmp_path: Path) -> None:
    class Exploding(FakeBox):
        def sleep(self, seconds: float) -> None:
            if seconds == 90:  # the hold of the fault below
                raise KeyboardInterrupt
            super().sleep(seconds)

    cam = FakeCamera()
    sc = scenario({"kind": "process_hang", "at": "1m", "unit": "slowboard", "hold": "90s"})
    with pytest.raises(KeyboardInterrupt):
        run(sc, Exploding("cam-x", runner=cam), tmp_path)
    stop = next(i for i, c in enumerate(cam.cmds) if "kill -STOP 4242" in c)
    cont = next(i for i, c in enumerate(cam.cmds) if "kill -CONT 4242" in c)
    assert cont > stop, "a frozen process must be resumed even if the run is interrupted"


def test_failed_revert_falls_back_to_reset(tmp_path: Path) -> None:
    cam = FakeCamera(fail_on="systemctl --user start sstcam-gatherer")
    sc = scenario({"kind": "gatherer_down", "at": "1m", "hold": "10s"})
    res = run(sc, box(cam), tmp_path)
    assert "revert_error" in res.labels[0].details
    assert any("start sstcam.target" in c for c in cam.cmds), "reset_to_nominal ran"


def test_refuses_unhealthy_camera(tmp_path: Path) -> None:
    cam = FakeCamera()
    cam.unhealthy.add("slowsignal")
    with pytest.raises(RuntimeError, match="not healthy"):
        run(scenario({"kind": "gatherer_down", "at": "1m"}), box(cam), tmp_path)
    assert not any("stop" in c for c in cam.cmds)


def test_no_recovery_aborts_remaining_faults(tmp_path: Path) -> None:
    cam = FakeCamera()

    class Breaking(FakeBox):
        def sh(self, cmd: str, **kw: object) -> str:  # type: ignore[override]
            if "kill -s SIGKILL" in cmd:
                cam.unhealthy.add("chiller")  # never comes back
            return super().sh(cmd, **kw)  # type: ignore[arg-type]

    sc = scenario(
        {"kind": "process_crash", "at": "1m", "unit": "chiller", "hold": "10s"},
        {"kind": "gatherer_down", "at": "5m"},
    )
    res = run(sc, Breaking("cam-x", runner=cam), tmp_path)
    assert res.aborted and "T-L01" in res.aborted
    assert len(res.labels) == 1 and not any("stop sstcam-gatherer" in c for c in cam.cmds)


def test_disk_full_refuses_real_disk() -> None:
    cam = FakeCamera(df="ext4 500000000000 400000000000")
    with pytest.raises(RuntimeError, match="refusing disk_full"):
        DiskFull(kind="disk_full", at="1m").inject(box(cam), Injected())
    assert not any("fallocate" in c for c in cam.cmds)


def test_chiller_ramp_steps_and_clears_override(tmp_path: Path) -> None:
    cam = FakeCamera()
    sc = scenario(
        {
            "kind": "chiller_ramp",
            "at": "1m",
            "to_c": 25,
            "start_c": 23,
            "over": "40s",
            "step": "10s",
            "hold": "10s",
        }
    )
    run(sc, box(cam), tmp_path)
    temps = [c.split()[-1] for c in cam.cmds if "mock temperature" in c]
    assert temps[:4] == ["23.50", "24.00", "24.50", "25.00"] and temps[4] == "0"
