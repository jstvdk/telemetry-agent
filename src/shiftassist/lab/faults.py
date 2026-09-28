"""Fault catalog for camera-in-a-box: how to inject, hold, revert and label each fault.

Every fault changes the *real* camera software's situation (a process killed or frozen, a file
missing, a sensor reading) and lets the camera's own code react; nothing is written into the
camera's logs by the harness. The label records what was done and when (container clock), plus
the detection events a correct detector should produce.
"""

import json
import shlex
from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from shiftassist.lab.box import Box
from shiftassist.sim.records import EventKind, ExpectedEvent
from shiftassist.sim.timeutil import parse_duration_ms

CONTROL = "/home/sstcam/lab-control/slowsignal.json"
CALIB = "/opt/sstcam/data/slowsignal/slowsig_calibration_coefficients_per_pixel_matched.csv"
FILL = "/data/.lab-fill"
PUBLISHERS = ("chiller", "slowboard", "slowsignal", "eventbuilder")  # monitoring sources


def iso(t: float) -> str:
    from datetime import UTC, datetime

    d = datetime.fromtimestamp(t, UTC)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def seconds(text: str) -> float:
    return parse_duration_ms(text) / 1000


class Injected(BaseModel):
    """What actually happened, in container time. Filled by inject/hold/revert."""

    t_inject: float = 0.0
    t_revert: float = 0.0
    details: dict[str, Any] = {}


class FaultBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    at: str  # offset from run start, e.g. '3m'
    hold: str = "60s"
    subsystem: ClassVar[str] = ""

    def inject(self, box: Box, st: Injected) -> None:
        raise NotImplementedError

    def during(self, box: Box, st: Injected) -> None:
        box.sleep(seconds(self.hold))

    def revert(self, box: Box, st: Injected) -> None:
        raise NotImplementedError

    def expected(self, box: Box, st: Injected) -> list[ExpectedEvent]:
        return []

    def root_cause(self) -> str:
        return ""

    def _ev(
        self,
        box: Box,
        kind: EventKind,
        subsystem: str,
        t: float,
        tol: float,
        channel: str | None = None,
        entity: str | None = None,
    ) -> ExpectedEvent:
        return ExpectedEvent(
            kind=kind,
            camera=box.name,
            subsystem=subsystem,
            near=iso(t),
            tolerance_s=tol,
            channel=channel,
            entity=entity,
        )


# --- process faults ----------------------------------------------------------------------------


class ProcessCrash(FaultBase):
    """SIGKILL a server; systemd restarts it. Chiller/slowboard come back *disconnected* (no
    monitoring) until someone reconnects: the hold is the time until the operator does."""

    kind: Literal["process_crash"]
    unit: Literal[
        "chiller",
        "slowboard",
        "slowsignal",
        "eventbuilder",
        "gatherer",
        "pointing",
        "target",
        "controller",
    ]
    signal: str = "SIGKILL"

    def inject(self, box: Box, st: Injected) -> None:
        st.details["pid_before"] = box.unit_props(self.unit, "MainPID").get("MainPID", "")
        st.t_inject = box.now()
        box.systemctl("kill", "-s", self.signal, box.unit(self.unit), action="inject")

    def revert(self, box: Box, st: Injected) -> None:
        if self.unit in ("chiller", "slowboard"):
            box.camera(self.unit, "connect", action="revert")
        st.t_revert = box.now()

    def expected(self, box: Box, st: Injected) -> list[ExpectedEvent]:
        ev = [self._ev(box, "restart", self.unit, st.t_inject, 30)]
        if self.unit in ("chiller", "slowboard"):
            ev.append(self._ev(box, "gap", self.unit, st.t_inject, 30))
        if self.unit == "slowsignal":
            ev.append(self._ev(box, "restart", "pointing", st.t_inject, 30))  # Requires=
        if self.unit == "gatherer":
            ev += [self._ev(box, "gap", s, st.t_inject, 30) for s in PUBLISHERS]
        return ev

    def root_cause(self) -> str:
        extra = (
            (
                " It restarted without reconnecting to the hardware, so its monitoring stopped "
                "until it was reconnected."
            )
            if self.unit in ("chiller", "slowboard")
            else ""
        )
        return (
            f"The {self.unit} server process was killed ({self.signal}) and restarted by "
            f"systemd.{extra}"
        )


class ProcessHang(FaultBase):
    """SIGSTOP a server for the hold time (a freeze: no exit, no journal entry), then SIGCONT."""

    kind: Literal["process_hang"]
    unit: Literal["chiller", "slowboard", "slowsignal", "eventbuilder", "gatherer"]

    def inject(self, box: Box, st: Injected) -> None:
        pid = box.unit_props(self.unit, "MainPID").get("MainPID", "0")
        if pid in ("", "0") and not box.dry_run:
            raise RuntimeError(f"{self.unit}: no main PID")
        st.details["pid"] = pid
        st.t_inject = box.now()
        box.sh(f"kill -STOP {pid}", action="inject")

    def revert(self, box: Box, st: Injected) -> None:
        box.sh(f"kill -CONT {st.details.get('pid', '0')}", check=False, action="revert")
        st.t_revert = box.now()

    def expected(self, box: Box, st: Injected) -> list[ExpectedEvent]:
        subs = PUBLISHERS if self.unit == "gatherer" else (self.unit,)
        return [self._ev(box, "gap", s, st.t_inject, 30) for s in subs]

    def root_cause(self) -> str:
        return (
            f"The {self.unit} server process was frozen (SIGSTOP) for {self.hold}: it did not "
            "exit, so systemd saw nothing wrong; its output simply stopped."
        )


class GathererDown(FaultBase):
    """The gatherer is stopped (e.g. by an operator) and started again after the hold."""

    kind: Literal["gatherer_down"]

    def inject(self, box: Box, st: Injected) -> None:
        st.t_inject = box.now()
        box.systemctl("stop", box.unit("gatherer"), action="inject")

    def revert(self, box: Box, st: Injected) -> None:
        box.systemctl("start", box.unit("gatherer"), action="revert")
        st.t_revert = box.now()

    def expected(self, box: Box, st: Injected) -> list[ExpectedEvent]:
        ev = [self._ev(box, "gap", s, st.t_inject, 30) for s in PUBLISHERS]
        return [*ev, self._ev(box, "restart", "gatherer", st.t_inject, seconds(self.hold) + 30)]

    def root_cause(self) -> str:
        return (
            "The gatherer was stopped: monitoring from every subsystem stopped being recorded "
            "and the central log stopped, although all other servers kept running."
        )


# --- configuration / data faults ----------------------------------------------------------------


class CalibrationMissing(FaultBase):
    """The slow-signal calibration table disappears (as after a bad update) and the server is
    restarted: it crash-loops, and pointing (Requires= slowsignal) goes down with it."""

    kind: Literal["calibration_missing"]

    def inject(self, box: Box, st: Injected) -> None:
        box.sh(f"mv {CALIB} {CALIB}.lab-hidden", action="inject")
        st.t_inject = box.now()
        box.systemctl("restart", box.unit("slowsignal"), check=False, action="inject")

    def revert(self, box: Box, st: Injected) -> None:
        box.sh(f"test -f {CALIB} || mv {CALIB}.lab-hidden {CALIB}", action="revert")
        box.systemctl(
            "reset-failed",
            box.unit("slowsignal"),
            box.unit("pointing"),
            check=False,
            action="revert",
        )
        box.systemctl("start", box.unit("slowsignal"), box.unit("pointing"), action="revert")
        st.t_revert = box.now()

    def expected(self, box: Box, st: Injected) -> list[ExpectedEvent]:
        return [
            self._ev(box, "traceback", "slowsignal", st.t_inject, 30),
            self._ev(box, "restart", "slowsignal", st.t_inject, 30),
            self._ev(box, "restart", "pointing", st.t_inject, 30),
            self._ev(box, "gap", "slowsignal", st.t_inject, 30),
        ]

    def root_cause(self) -> str:
        return (
            "The slow-signal calibration file was missing when the slow-signal server "
            "restarted: FileNotFoundError at start-up, crash loop, and the pointing server "
            "(which requires slow-signal) was stopped each time."
        )


class DiskFull(FaultBase):
    """Fill the data volume. Refuses unless /data is a small tmpfs (never fill a real disk)."""

    kind: Literal["disk_full"]
    max_volume_gib: float = 4.0

    def inject(self, box: Box, st: Injected) -> None:
        out = box.sh("df -B1 --output=fstype,size,avail /data | tail -1", root=True, action="probe")
        if not box.dry_run:
            fstype, size, avail = out.split()
            if fstype != "tmpfs" or int(size) > self.max_volume_gib * 2**30:
                raise RuntimeError(
                    f"refusing disk_full: /data is {fstype} {int(size) / 2**30:.1f} GiB "
                    "(needs a small tmpfs; start the box with DATA_TMPFS=…)"
                )
            st.details["avail_before"] = int(avail)
        st.t_inject = box.now()
        box.sh(
            f"fallocate -l $(( $(df -B1 --output=avail /data | tail -1) - 65536 )) {FILL} "
            f"|| true; chown sstcam: {FILL}",
            root=True,
            action="inject",
        )

    def revert(self, box: Box, st: Injected) -> None:
        box.sh(f"rm -f {FILL}", root=True, action="revert")
        st.t_revert = box.now()

    def root_cause(self) -> str:
        return "The data volume was full; writes of logs and monitoring files failed."


# --- slow-signal (per TARGET module) faults, via the lab model's control file ------------------


class _SlowSignalFault(FaultBase):
    module: int = Field(ge=0, le=31)
    sensors: list[str] = ["sipm1"]

    def _entry(self, st: Injected) -> dict[str, Any]:
        raise NotImplementedError

    def _set(self, box: Box, faults: list[dict[str, Any]], action: str) -> None:
        box.write_file(CONTROL, json.dumps({"mode": "realistic", "faults": faults}), action=action)

    def inject(self, box: Box, st: Injected) -> None:
        st.t_inject = box.now()
        self._set(box, [self._entry(st)], "inject")

    def revert(self, box: Box, st: Injected) -> None:
        self._set(box, [], "revert")
        st.t_revert = box.now()

    @property
    def entity(self) -> str:
        return f"tm{self.module:02d}"


class SlowSignalDrift(_SlowSignalFault):
    kind: Literal["slowsignal_drift"]
    slope_c_per_h: float = 3.0

    def _entry(self, st: Injected) -> dict[str, Any]:
        return {
            "type": "drift",
            "module": self.module,
            "sensors": self.sensors,
            "slope_c_per_h": self.slope_c_per_h,
            "since": st.t_inject,
        }

    def expected(self, box: Box, st: Injected) -> list[ExpectedEvent]:
        return [
            self._ev(
                box,
                "trend",
                "slowsignal",
                st.t_inject + seconds(self.hold) / 2,
                seconds(self.hold) / 2 + 30,
                channel=f"temperature_{s}",
                entity=self.entity,
            )
            for s in self.sensors
            if "*" not in s
        ]

    def root_cause(self) -> str:
        return (
            f"Temperature of {', '.join(self.sensors)} on TARGET module {self.module} rose "
            f"steadily at {self.slope_c_per_h} °C/h (e.g. degraded cooling of that module)."
        )


class SensorFault(_SlowSignalFault):
    kind: Literal["sensor_fault"]
    bits: int = 0x80  # 'Sensor Hard Fault: Open or Short RTD or RSENSE'

    def _entry(self, st: Injected) -> dict[str, Any]:
        return {
            "type": "sensor_fault",
            "module": self.module,
            "sensors": self.sensors,
            "bits": self.bits,
        }

    def expected(self, box: Box, st: Injected) -> list[ExpectedEvent]:
        return [self._ev(box, "log_burst", "slowsignal", st.t_inject, 30, entity=self.entity)]

    def root_cause(self) -> str:
        return (
            f"The {', '.join(self.sensors)} RTD sensor on TARGET module {self.module} failed "
            "(open/short): one hardware-error WARNING per packet. The log line does not name "
            "the module or sensor."
        )


class ModuleDead(_SlowSignalFault):
    kind: Literal["module_dead"]

    def _entry(self, st: Injected) -> dict[str, Any]:
        return {"type": "dead", "module": self.module}

    def expected(self, box: Box, st: Injected) -> list[ExpectedEvent]:
        return [self._ev(box, "gap", "slowsignal", st.t_inject, 30, entity=self.entity)]

    def root_cause(self) -> str:
        return f"TARGET module {self.module} stopped sending slow-signal packets (e.g. lost power)."


# --- chiller ------------------------------------------------------------------------------------


class ChillerRamp(FaultBase):
    """Chiller temperatures ramp linearly to ``to_c`` over ``over``, stay for ``hold``, and the
    override is cleared (the mock treats 0 as 'no override')."""

    kind: Literal["chiller_ramp"]
    to_c: float = 30.0
    start_c: float = 23.0  # mock room temperature when the chiller is not running
    over: str = "5m"
    step: str = "10s"

    def inject(self, box: Box, st: Injected) -> None:
        st.t_inject = box.now()
        n = max(1, int(seconds(self.over) / seconds(self.step)))
        for i in range(1, n + 1):
            value = self.start_c + (self.to_c - self.start_c) * i / n
            box.camera("chiller", "mock", "temperature", f"{value:.2f}", action="inject")
            if i < n:
                box.sleep(seconds(self.step))
        st.details["top_reached"] = box.now()

    def revert(self, box: Box, st: Injected) -> None:
        box.camera("chiller", "mock", "temperature", "0", action="revert")
        st.t_revert = box.now()

    def expected(self, box: Box, st: Injected) -> list[ExpectedEvent]:
        mid = st.t_inject + seconds(self.over) / 2
        return [
            self._ev(
                box,
                "trend",
                "chiller",
                mid,
                seconds(self.over) / 2 + 30,
                channel=f"{c}_temperature",
            )
            for c in ("supply", "return")
        ]

    def root_cause(self) -> str:
        return (
            f"Chiller temperatures rose from {self.start_c} to {self.to_c} °C over "
            f"{self.over} (e.g. cooling capacity lost)."
        )


Fault = Annotated[
    ProcessCrash
    | ProcessHang
    | GathererDown
    | CalibrationMissing
    | DiskFull
    | SlowSignalDrift
    | SensorFault
    | ModuleDead
    | ChillerRamp,
    Field(discriminator="kind"),
]


def reset_to_nominal(box: Box) -> None:
    """Idempotent: undo every fault this catalog can leave behind, whatever state the run
    was in. Used after each fault's own revert fails, and by `shiftassist-lab reset`."""
    box.write_file(CONTROL, json.dumps({"mode": "realistic", "faults": []}), action="reset")
    box.sh(f"test -f {CALIB} || mv {CALIB}.lab-hidden {CALIB} || true", action="reset")
    box.sh(f"rm -f {FILL}", root=True, action="reset")
    box.sh("pkill -CONT -u sstcam -f sstcam || true", action="reset")
    box.systemctl("reset-failed", check=False, action="reset")
    box.systemctl("start", "sstcam.target", check=False, action="reset")
    box.camera("chiller", "mock", "temperature", "0", action="reset")
    for unit in ("chiller", "slowboard"):
        box.sh(f"sstcam {shlex.quote(unit)} connect || true", action="reset")
