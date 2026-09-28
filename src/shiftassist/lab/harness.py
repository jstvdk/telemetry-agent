"""Run a tier-B scenario against a camera-in-a-box: faults on a schedule, always reverted, labelled.

For each fault, in order:
  1. wait until its offset from the run start (container clock)
  2. inject → hold → revert (the revert runs in `finally`, whatever happened)
  3. write its label (actual container times, expected detection events)
  4. verify recovery (no failed units, everything active) before the next fault;
     if the camera does not recover, reset to nominal and stop the run.

Preconditions refuse to start on a camera that is not healthy, so labels never describe faults
injected on top of an unknown state.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from shiftassist.lab.box import Box
from shiftassist.lab.faults import Fault, Injected, iso, reset_to_nominal, seconds
from shiftassist.sim.records import Label

CAMERA_UNITS = (
    "gatherer",
    "chiller",
    "slowboard",
    "slowsignal",
    "eventbuilder",
    "eventbuilder-mock",
    "controller",
    "pointing",
    "target",
)


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    title: str
    description: str = ""
    settle: str = "2m"  # healthy time recorded before the first fault
    cooldown: str = "2m"  # healthy time recorded after the last fault
    recover_timeout: str = "90s"
    faults: list[Fault]

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        ats = [seconds(f.at) for f in self.faults]
        if ats != sorted(ats):
            raise ValueError("faults must be listed in time order")
        if ats and ats[0] < seconds(self.settle):
            raise ValueError("first fault must come after the settle period")
        return self


def load_scenario(path: str | Path) -> Scenario:
    return Scenario.model_validate(yaml.safe_load(Path(path).read_text()))


class RunResult(BaseModel):
    scenario: str
    container: str
    t_start: float
    t_end: float
    labels: list[Label]
    aborted: str | None = None


def check_healthy(box: Box) -> list[str]:
    problems = [f"failed unit: {u}" for u in box.failed_units()]
    for u in CAMERA_UNITS:
        state = box.unit_props(u, "ActiveState").get("ActiveState", "")
        if state != "active" and not box.dry_run:
            problems.append(f"{u}: {state or 'unknown'}")
    return problems


def wait_healthy(box: Box, timeout_s: float) -> list[str]:
    deadline = box.now() + timeout_s
    while True:
        problems = check_healthy(box)
        if not problems or box.now() >= deadline:
            return problems
        box.sleep(5)


def run(scenario: Scenario, box: Box, out_dir: Path) -> RunResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    problems = check_healthy(box)
    if problems:
        raise RuntimeError(f"camera not healthy, refusing to start: {problems}")

    t_start = box.now()
    labels: list[Label] = []
    aborted: str | None = None
    labels_path = out_dir / "labels.jsonl"
    labels_path.write_text("")

    for idx, fault in enumerate(scenario.faults):
        box.sleep(t_start + seconds(fault.at) - box.now())
        st = Injected()
        try:
            fault.inject(box, st)
            fault.during(box, st)
        finally:
            try:
                fault.revert(box, st)
            except Exception as e:  # revert failed: fall back to the catalog-wide reset
                st.details["revert_error"] = str(e)
                reset_to_nominal(box)
                st.t_revert = st.t_revert or box.now()

        label = Label(
            label_id=f"{scenario.id}-L{idx + 1:02d}",
            scenario=scenario.id,
            fault_index=idx,
            group=f"{scenario.id}-F{idx:02d}",
            kind=fault.kind,
            camera=box.name,
            subsystem=getattr(fault, "unit", None) or _subsystem(fault.kind),
            start=iso(st.t_inject),
            end=iso(st.t_revert),
            root_cause=fault.root_cause(),
            expected_events=fault.expected(box, st),
            details={"fault": fault.model_dump(), **st.details},
        )
        labels.append(label)
        with labels_path.open("a") as fh:
            fh.write(label.model_dump_json() + "\n")

        problems = wait_healthy(box, seconds(scenario.recover_timeout))
        if problems:
            aborted = f"no recovery after {label.label_id}: {problems}"
            reset_to_nominal(box)
            break

    if aborted is None:
        box.sleep(seconds(scenario.cooldown))
    result = RunResult(
        scenario=scenario.id,
        container=box.name,
        t_start=t_start,
        t_end=box.now(),
        labels=labels,
        aborted=aborted,
    )
    (out_dir / "run.json").write_text(
        json.dumps(
            {
                "scenario": scenario.model_dump(mode="json"),
                "container": box.name,
                "start": iso(t_start),
                "end": iso(result.t_end),
                "aborted": aborted,
                "written": datetime.now().astimezone().isoformat(timespec="seconds"),
            },
            indent=2,
        )
        + "\n"
    )
    return result


def _subsystem(kind: str) -> str:
    return {
        "gatherer_down": "gatherer",
        "calibration_missing": "slowsignal",
        "disk_full": "os",
        "chiller_ramp": "chiller",
    }.get(kind, "slowsignal")
