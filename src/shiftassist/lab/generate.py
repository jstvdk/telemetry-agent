"""Generate a held-out fault scenario from a seed (the B03 protocol, PROVENANCE D-18e).

    shiftassist-lab-generate SEED [--extra FAULT.yaml ...] [--id B03] -o scenario.yaml

The seed is the first 8 hex digits of the commit that freezes the runbook, so nobody (the author,
the assistant) can know the scenario while writing the runbook or tuning the detector. This file
is committed before that commit exists.

What is drawn: order, units, modules, sensors, magnitudes, holds, gaps, and which compatible
faults overlap. What is fixed: every catalog type at least once; three more faults of random
types; at least two overlapping pairs starting 5-20 s apart; `--extra` faults (types written
after the freeze, with no runbook entry) inserted at random positions, never overlapping.
"""

import argparse
import random
from pathlib import Path
from typing import Any

import yaml

from shiftassist.lab.faults import seconds
from shiftassist.lab.harness import Scenario

GENERATOR_VERSION = 1
SENSORS = ["prim_asics", "aux_asics", "prim_shaper", "aux_shaper", "sipm1", "sipm2", "sipm3",
           "sipm4", "preamp"]  # fmt: skip
CRASH_UNITS = ["chiller", "slowboard", "slowsignal", "eventbuilder", "gatherer", "pointing",
               "target", "controller"]  # fmt: skip
HANG_UNITS = ["chiller", "slowboard", "slowsignal", "eventbuilder", "gatherer"]
CATALOG = ["process_crash", "process_hang", "gatherer_down", "calibration_missing", "disk_full",
           "slowsignal_drift", "sensor_fault", "module_dead", "chiller_ramp"]  # fmt: skip
EXTRA_RANDOM = 3
PAIRS = 2
SETTLE_S, RECOVER_S = 180, 90  # quiet before the first fault; time allowed for recovery


def _draw(kind: str, r: random.Random) -> dict[str, Any]:

    def s(a: int, b: int) -> str:
        return f"{r.randint(a, b)}s"

    match kind:
        case "process_crash":
            return {"kind": kind, "unit": r.choice(CRASH_UNITS), "hold": s(20, 90)}
        case "process_hang":
            return {"kind": kind, "unit": r.choice(HANG_UNITS), "hold": s(30, 90)}
        case "gatherer_down":
            return {"kind": kind, "hold": s(30, 120)}
        case "calibration_missing":
            return {"kind": kind, "hold": s(30, 75)}
        case "disk_full":
            return {"kind": kind, "hold": s(60, 120)}
        case "slowsignal_drift":
            slope = round(r.choice([-1, 1]) * 10 ** r.uniform(0.15, 0.9), 2)  # 1.4 … 8 °C/h
            return {"kind": kind, "module": r.randint(0, 31), "sensors": [r.choice(SENSORS)],
                    "slope_c_per_h": slope, "hold": s(240, 420)}  # fmt: skip
        case "sensor_fault" | "module_dead":
            return {"kind": kind, "module": r.randint(0, 31), "sensors": [r.choice(SENSORS)],
                    "hold": s(60, 120)}  # fmt: skip
        case "chiller_ramp":
            return {"kind": kind, "to_c": round(r.uniform(25, 30), 1), "over": s(180, 360),
                    "hold": "60s"}  # fmt: skip
    raise ValueError(kind)


def _duration(f: dict[str, Any]) -> float:
    return seconds(f.get("hold", "60s")) + (seconds(f["over"]) if "over" in f else 0)


def _compatible(a: dict[str, Any], b: dict[str, Any]) -> bool:
    try:
        Scenario.model_validate(
            {
                "id": "x",
                "title": "x",
                "settle": "0s",
                "faults": [{**a, "at": "0s"}, {**b, "at": "10s", "overlap": True}],
            }
        )
    except ValueError:
        return False
    return True


def generate(
    seed: str, extra: list[dict[str, Any]] | None = None, sid: str = "B03"
) -> dict[str, Any]:
    r = random.Random(int(seed, 16))
    faults = [_draw(k, r) for k in CATALOG]
    faults += [_draw(r.choice(CATALOG), r) for _ in range(EXTRA_RANDOM)]
    r.shuffle(faults)

    # pick overlapping pairs among compatible neighbours; each fault in at most one pair
    units: list[list[dict[str, Any]]] = [[f] for f in faults]
    made = 0
    for _ in range(200):
        if made == PAIRS:
            break
        i = r.randrange(len(units) - 1)
        a, b = units[i], units[i + 1]
        if len(a) == 1 and len(b) == 1 and _compatible(a[0], b[0]):
            units[i : i + 2] = [[a[0], {**b[0], "overlap": True}]]
            made += 1
    if made < PAIRS:
        raise RuntimeError(f"seed {seed}: could not form {PAIRS} overlapping pairs")
    for f in extra or []:
        units.insert(r.randrange(len(units) + 1), [dict(f)])

    t: float = SETTLE_S
    out: list[dict[str, Any]] = []
    for group in units:
        start = t
        end = start
        for j, f in enumerate(group):
            at: float = start if j == 0 else start + r.randint(5, 20)
            if j:  # the second fault must start while the first is still held
                first_hold = seconds(group[0]["hold"])
                f["hold"] = f"{max(seconds(f['hold']), 30):.0f}s"
                at = min(at, start + first_hold - 5)
            out.append({**f, "at": f"{at:.0f}s"})
            end = max(end, at + _duration(f))
        t = int(end) + RECOVER_S + r.randint(60, 150)
    sc = {
        "id": sid,
        "title": f"Held-out faults, generated (seed {seed}, generator v{GENERATOR_VERSION})",
        "description": (
            "Generated by shiftassist.lab.generate from the runbook-freeze commit; not edited by "
            "hand. Every catalog type, three random extras, two overlapping pairs"
            + (f", {len(extra)} fault(s) of types written after the freeze." if extra else ".")
        ),
        "settle": f"{SETTLE_S}s",
        "cooldown": "3m",
        "faults": out,
    }
    Scenario.model_validate(sc)  # must be runnable as generated
    return sc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="shiftassist-lab-generate", description=__doc__)
    p.add_argument("seed", help="hex, e.g. the first 8 digits of the runbook-freeze commit")
    p.add_argument("--extra", nargs="*", default=[], help="YAML files, one fault each")
    p.add_argument("--id", default="B03")
    p.add_argument("-o", "--out", required=True)
    a = p.parse_args(argv)
    extra = [yaml.safe_load(Path(x).read_text()) for x in a.extra]
    sc = generate(a.seed, extra, a.id)
    Path(a.out).write_text(yaml.safe_dump(sc, sort_keys=False, width=100))
    total = seconds(sc["faults"][-1]["at"]) / 60
    print(f"{a.out}: {len(sc['faults'])} faults, last at {total:.0f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
