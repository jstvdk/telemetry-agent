"""Run a scenario: nominal telemetry → faults → nominal logs → blackouts → sorted stream.

Order matters. Faults change telemetry before the nominal status lines are written, so
status lines report the values the fault produced. Blackouts are applied last and only to
nominal records: a fault's own log lines always survive.
"""

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shiftassist import __version__
from shiftassist.sim.context import Blackout, SimContext
from shiftassist.sim.faults import INJECTORS
from shiftassist.sim.nominal import (
    BENIGN_WARNINGS,
    CHANNELS,
    CONFIG_PATH,
    GOOD_CONFIG_HASH,
    SUBSYSTEMS,
)
from shiftassist.sim.records import Label, Level, LogRecord, Record, TelemetryRecord, subsystem_of
from shiftassist.sim.scenario import Scenario
from shiftassist.sim.timeutil import iso

MIN = 60_000
TRAP_LINES = (
    ("daq", "self-check complete: NO_ERROR flag set"),
    ("readout", "board scan done, errors_suppressed=0 last_error=none"),
    ("hv", "interlock self-test passed (fault_count=0, ERROR_LATCH clear)"),
)


@dataclass(frozen=True)
class SimResult:
    scenario: Scenario
    seed: int
    records: list[Record]
    labels: list[Label]


def generate(scenario: Scenario, seed: int | None = None) -> SimResult:
    seed = scenario.seed if seed is None else seed
    ctx = SimContext(scenario, seed)

    for idx, fault in enumerate(scenario.faults):
        rng = ctx.rng("jitter", idx)
        for cam in fault.cameras or scenario.cameras:
            t0 = fault.at_ms + (rng.randint(0, fault.jitter_ms) if fault.jitter_ms else 0)
            INJECTORS[fault.kind](ctx, fault, idx, cam, t0)

    nominal: list[Record] = []
    for cam in scenario.cameras:
        nominal.extend(_nominal_logs(ctx, cam))
        for ch, model in CHANNELS.items():
            series = ctx.tm[(cam, ch)]
            nominal.extend(
                TelemetryRecord(t, cam, ch, round(v, model.decimals))
                for t, v in zip(ctx.grid, series, strict=True)
            )

    kept = [r for r in nominal if not _blacked_out(r, ctx.blackouts)]
    records: list[Record] = sorted([*kept, *ctx.fault_logs], key=lambda r: r.t_ms)  # stable
    return SimResult(scenario, seed, records, ctx.labels)


def _blacked_out(r: Record, blackouts: list[Blackout]) -> bool:
    for b in blackouts:
        if r.camera != b.camera or not b.t0 <= r.t_ms < b.t1:
            continue
        if isinstance(r, TelemetryRecord) and not b.telemetry:
            continue
        if b.subsystems is None or subsystem_of(r) in b.subsystems:
            return True
    return False


def _nominal_logs(ctx: SimContext, cam: str) -> list[LogRecord]:
    rng = ctx.rng("logs", cam)
    noise = ctx.scenario.noise
    dur = ctx.duration_ms
    out: list[LogRecord] = []

    def add(t: int, sub: str, level: Level, text: str) -> None:
        if 0 <= t < dur:
            out.append(LogRecord(t, cam, sub, level, text))

    add(
        1000,
        "config",
        "INFO",
        f"config loaded from {CONFIG_PATH} hash={GOOD_CONFIG_HASH} buffer_size=8192",
    )
    add(5000, "daq", "INFO", "run 0042 started")

    for sub in SUBSYSTEMS:
        if sub == "config":
            continue
        for seq, t in enumerate(range(0, dur, MIN)):
            add(t + rng.randint(0, 500), sub, "INFO", f"heartbeat seq={seq} status=OK")

    for t in range(2 * MIN, dur, 5 * MIN):
        temp = ctx.value_at(cam, "cooling.plate_temp_c", t)
        flow = ctx.value_at(cam, "cooling.coolant_flow_lpm", t)
        counter = " error_count=0" if noise.trap_lines else ""
        add(
            t + 200,
            "cooling",
            "INFO",
            f"status ok{counter} plate_temp={temp:.2f}C flow={flow:.2f}lpm",
        )

    events = 0.0
    for t in range(10 * MIN, dur, 10 * MIN):
        rate = ctx.value_at(cam, "daq.event_rate_hz", t)
        events += rate * 600
        add(
            t + 300,
            "daq",
            "INFO",
            f"run 0042 progress events={int(events)} rate={rate:.0f}Hz dropped=0",
        )

    for t in range(MIN, dur, 2 * MIN):
        add(t + 700, "readout", "DEBUG", f"fifo fill={rng.randint(5, 25)}%")

    for t in range(7 * MIN, dur, 15 * MIN):
        add(t, "os", "INFO", f"chrony offset={rng.uniform(-0.8, 0.8):+.1f}ms")

    if noise.trap_lines:
        every = max(1, 30 // noise.trap_multiplier) * MIN
        for k, t in enumerate(range(every // 2, dur, every)):
            sub, text = TRAP_LINES[k % len(TRAP_LINES)]
            add(t + rng.randint(0, 5000), sub, "INFO", text)

    hours = dur / 3_600_000
    for _ in range(_poisson(rng.random, noise.benign_warnings_per_hour * hours)):
        sub, template = BENIGN_WARNINGS[rng.randrange(len(BENIGN_WARNINGS))]
        text = template.format(
            ms=rng.randint(80, 200), off=rng.uniform(1.0, 3.0), q=rng.randint(60, 80)
        )
        add(rng.randint(0, dur - 1), sub, "WARNING", text)

    return out


def _poisson(uniform: Callable[[], float], lam: float) -> int:
    """Knuth's method; lam is small here (a few per scenario)."""
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= uniform()
        if p <= limit:
            return k
        k += 1


# --- serialisation --------------------------------------------------------------------------


def record_to_dict(r: Record, sc: Scenario) -> dict[str, Any]:
    ts = iso(sc.start, r.t_ms)
    if isinstance(r, LogRecord):
        return {
            "type": "log",
            "ts": ts,
            "camera": r.camera,
            "subsystem": r.subsystem,
            "level": r.level,
            "text": r.text,
        }
    return {"type": "tm", "ts": ts, "camera": r.camera, "channel": r.channel, "value": r.value}


def write(result: SimResult, out_dir: str | Path) -> dict[str, Any]:
    """Write stream.jsonl, labels.jsonl and manifest.json; return the manifest."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    sc = result.scenario

    stream = "".join(
        json.dumps(record_to_dict(r, sc), ensure_ascii=False) + "\n" for r in result.records
    )
    labels = "".join(lb.model_dump_json() + "\n" for lb in result.labels)
    (out / "stream.jsonl").write_text(stream)
    (out / "labels.jsonl").write_text(labels)

    manifest = {
        "scenario": sc.model_dump(mode="json"),
        "seed": result.seed,
        "generator": f"shiftassist.sim {__version__}",
        "counts": {
            "logs": sum(isinstance(r, LogRecord) for r in result.records),
            "telemetry": sum(isinstance(r, TelemetryRecord) for r in result.records),
            "labels": len(result.labels),
        },
        "sha256": {
            "stream.jsonl": hashlib.sha256(stream.encode()).hexdigest(),
            "labels.jsonl": hashlib.sha256(labels.encode()).hexdigest(),
        },
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
