"""Fault injectors. Each one changes telemetry, adds log lines and writes its own label.

Every injector gets the camera and the (jittered) start time ``t0`` in ms. Anything an
injector changes must be described in its label, because labels are the only ground truth
the evaluation has.
"""

import math
from collections.abc import Callable
from typing import Any

from shiftassist.sim.context import SimContext
from shiftassist.sim.nominal import CONFIG_PATH, GOOD_CONFIG_HASH
from shiftassist.sim.scenario import (
    ConfigReloadCrash,
    CoolingDrift,
    DiskFull,
    HVTrip,
    NetworkDrop,
    NewSignature,
    PromptInjection,
)
from shiftassist.sim.timeutil import parse_duration_ms

HV_CURRENT_LIMIT_UA = 150.0
HV_NOMINAL_V = 1100.0
HV_RAMP_MS = 120_000
MIN = 60_000


def cooling_drift(ctx: SimContext, f: CoolingDrift, idx: int, cam: str, t0: int) -> None:
    end = t0 + parse_duration_ms(f.duration) if f.duration else ctx.duration_ms
    slope_per_ms = f.slope_c_per_h / 3_600_000
    span = max(1, end - t0)
    ctx.apply(cam, "cooling.plate_temp_c", t0, end, lambda t, v: v + slope_per_ms * (t - t0))
    ctx.apply(
        cam, "cooling.plate_temp_c", end, ctx.duration_ms, lambda t, v: v + slope_per_ms * span
    )
    ctx.apply(
        cam,
        "cooling.coolant_flow_lpm",
        t0,
        ctx.duration_ms,
        lambda t, v: v - f.flow_drop_lpm * min(1.0, (t - t0) / span),
    )
    ctx.label(
        fault_index=idx,
        kind="cooling_drift",
        camera=cam,
        subsystem="cooling",
        t0=t0,
        t1=end,
        root_cause=(
            f"coolant flow degrading by {f.flow_drop_lpm} lpm; "
            f"plate temperature rising {f.slope_c_per_h} °C/h"
        ),
        # A trend is only detectable once it stands out from noise: accept the first hour.
        expected=[ctx.expect("trend", cam, "cooling", t0 + 30 * MIN, 1800, "cooling.plate_temp_c")],
        details={
            "channel": "cooling.plate_temp_c",
            "slope_c_per_h": f.slope_c_per_h,
            "flow_drop_lpm": f.flow_drop_lpm,
        },
    )


def config_reload_crash(ctx: SimContext, f: ConfigReloadCrash, idx: int, cam: str, t0: int) -> None:
    rng = ctx.rng("fault", idx, cam)
    bad_hash = f"{rng.getrandbits(28):07x}"
    t_crash = t0 + parse_duration_ms(f.crash_after)
    t_restart = t_crash + parse_duration_ms(f.restart_after)

    ctx.log(
        t0,
        cam,
        "config",
        "INFO",
        f"config reloaded by user=operator from {CONFIG_PATH} hash={bad_hash} "
        f"buffer_size={f.bad_buffer_size} (was {f.good_buffer_size})",
    )
    ctx.log(
        t_crash, cam, "readout", "ERROR", _buffer_traceback(f.good_buffer_size, f.bad_buffer_size)
    )
    ctx.log(
        t_crash + 1000,
        cam,
        "readout",
        "CRITICAL",
        "readout worker exited with code 1 (unhandled BufferSizeMismatch)",
    )
    ctx.log(
        t_restart,
        cam,
        "readout",
        "WARNING",
        f"readout worker restarted by supervisor pid={rng.randint(20000, 60000)} restart_count=1",
    )
    ctx.log(
        t_restart + 2000,
        cam,
        "config",
        "WARNING",
        f"config validation failed for hash={bad_hash} (buffer_size={f.bad_buffer_size} < "
        f"frame size {f.good_buffer_size}); falling back to last known good "
        f"hash={GOOD_CONFIG_HASH} buffer_size={f.good_buffer_size}",
    )
    ctx.log(t_restart + 5000, cam, "readout", "INFO", "readout worker running, boards=12/12 ok")

    for ch in ("readout.trigger_rate_hz", "daq.event_rate_hz"):
        ctx.apply(cam, ch, t_crash, t_restart, lambda t, v: 0.0)
    ctx.blackout(cam, t_crash, t_restart, subsystems=["readout"])

    ctx.label(
        fault_index=idx,
        kind="readout_crash",
        camera=cam,
        subsystem="readout",
        t0=t0,
        t1=t_restart + 5000,
        root_cause=(
            f"config reload at {ctx.iso(t0)} set buffer_size={f.bad_buffer_size}, smaller than "
            f"the {f.good_buffer_size}-byte frame; the readout worker raised BufferSizeMismatch "
            f"at {ctx.iso(t_crash)} and the supervisor restarted it with the last known good config"
        ),
        expected=[
            ctx.expect("config_change", cam, "config", t0, 5),
            ctx.expect("traceback", cam, "readout", t_crash, 5),
            ctx.expect("restart", cam, "readout", t_restart, 10),
        ],
        details={
            "bad_config_hash": bad_hash,
            "good_config_hash": GOOD_CONFIG_HASH,
            "bad_buffer_size": f.bad_buffer_size,
            "good_buffer_size": f.good_buffer_size,
            "crash_at": ctx.iso(t_crash),
            "restart_at": ctx.iso(t_restart),
            "runbook": "RB-readout-buffer",
        },
    )

    if f.distractor:
        center = t_crash - 3 * MIN
        width = 2 * MIN
        ctx.apply(
            cam,
            "cooling.plate_temp_c",
            center - 3 * width,
            center + 3 * width,
            lambda t, v: v + 0.35 * math.exp(-0.5 * ((t - center) / width) ** 2),
        )
        ctx.label(
            fault_index=idx,
            kind="distractor",
            camera=cam,
            subsystem="cooling",
            t0=center - 3 * width,
            t1=center + 3 * width,
            root_cause="harmless +0.35 °C thermal fluctuation within limits; unrelated to the "
            "readout crash",
            expected=[],
            details={
                "channel": "cooling.plate_temp_c",
                "peak_delta_c": 0.35,
                "peak_at": ctx.iso(center),
            },
        )


def hv_trip(ctx: SimContext, f: HVTrip, idx: int, cam: str, t0: int) -> None:
    rise = MIN
    t_rec = t0 + parse_duration_ms(f.recover_after)
    base = ctx.value_at(cam, "hv.current_ua", t0 - rise)
    ramp = rise - ctx.interval_ms  # the last sample before the trip is at the peak
    ctx.apply(
        cam,
        "hv.current_ua",
        t0 - rise,
        t0,
        lambda t, v: v + (f.peak_current_ua - base) * min(1.0, (t - (t0 - rise)) / ramp),
    )
    for ch in ("hv.current_ua", "hv.voltage_v"):
        ctx.apply(cam, ch, t0, t_rec, lambda t, v: 0.0)
        ctx.apply(cam, ch, t_rec, t_rec + HV_RAMP_MS, lambda t, v: v * (t - t_rec) / HV_RAMP_MS)

    warn_value = base + (f.peak_current_ua - base) * min(1.0, (rise - 20_000) / ramp)
    ctx.log(
        t0 - 20_000,
        cam,
        "hv",
        "WARNING",
        f"HV ch{f.channel} current rising {warn_value:.1f} uA (limit {HV_CURRENT_LIMIT_UA} uA)",
    )
    ctx.log(
        t0,
        cam,
        "hv",
        "ERROR",
        f"HV trip on channel {f.channel}: overcurrent {f.peak_current_ua:.1f} uA > limit "
        f"{HV_CURRENT_LIMIT_UA} uA, channel switched off",
    )
    ctx.log(t_rec, cam, "hv", "INFO", f"HV ramp-up started ch{f.channel}")
    ctx.log(
        t_rec + HV_RAMP_MS,
        cam,
        "hv",
        "INFO",
        f"HV ramp-up complete ch{f.channel} at {HV_NOMINAL_V} V",
    )

    ctx.label(
        fault_index=idx,
        kind="hv_trip",
        camera=cam,
        subsystem="hv",
        t0=t0 - rise,
        t1=t_rec + HV_RAMP_MS,
        root_cause=f"overcurrent on HV channel {f.channel} (peak {f.peak_current_ua} uA > "
        f"{HV_CURRENT_LIMIT_UA} uA); channel tripped and was ramped back up",
        expected=[ctx.expect("limit", cam, "hv", t0 - 10_000, 30, "hv.current_ua")],
        details={
            "hv_channel": f.channel,
            "peak_current_ua": f.peak_current_ua,
            "trip_at": ctx.iso(t0),
            "recovered_at": ctx.iso(t_rec + HV_RAMP_MS),
        },
    )


def network_drop(ctx: SimContext, f: NetworkDrop, idx: int, cam: str, t0: int) -> None:
    dur = parse_duration_ms(f.duration)
    t1 = t0 + dur
    ctx.blackout(cam, t0, t1, subsystems=None, telemetry=True)
    # Logged locally while the link was down and delivered after reconnection.
    ctx.log(
        t1 + 500,
        cam,
        "os",
        "WARNING",
        f"network link eth0 was down for {dur / 1000:.1f} s (carrier lost at {ctx.iso(t0)})",
    )
    ctx.log(
        t1 + 800,
        cam,
        "daq",
        "INFO",
        f"reconnected to tcp://daq-server:6000 after {dur / 1000:.1f} s",
    )
    ctx.label(
        fault_index=idx,
        kind="network_drop",
        camera=cam,
        subsystem="network",
        t0=t0,
        t1=t1,
        root_cause=f"network link loss for {dur / 1000:.0f} s; all logs and telemetry interrupted",
        expected=[ctx.expect("gap", cam, "network", t0, 300)],
        details={"duration_s": dur / 1000},
    )


def disk_full(ctx: SimContext, f: DiskFull, idx: int, cam: str, t0: int) -> None:
    ch = "os.disk_used_pct"
    fill = parse_duration_ms(f.fill_duration)
    t_full = t0 + fill
    t_purge = t_full + parse_duration_ms(f.stall)
    v0 = ctx.value_at(cam, ch, t0)

    def crossing(pct: float) -> int:
        return t0 + round((pct - v0) / (100.0 - v0) * fill)

    ctx.apply(cam, ch, t0, t_full, lambda t, v: v0 + (100.0 - v0) * (t - t0) / fill)
    ctx.apply(cam, ch, t_full, t_purge, lambda t, v: 100.0)
    ctx.apply(
        cam, ch, t_purge, ctx.duration_ms, lambda t, v: 58.0 + 0.2 * (t - t_purge) / 3_600_000
    )
    ctx.apply(cam, "daq.event_rate_hz", t_full, t_purge, lambda t, v: 0.0)

    ctx.log(crossing(90), cam, "os", "WARNING", "disk usage 90% on /data")
    ctx.log(crossing(98), cam, "os", "WARNING", "disk usage 98% on /data")
    ctx.log(
        t_full,
        cam,
        "daq",
        "ERROR",
        "Traceback (most recent call last):\n"
        '  File "/opt/cam/daq/writer.py", line 88, in flush\n'
        "    self._fh.write(block)\n"
        "OSError: [Errno 28] No space left on device: '/data/run_0042/events_0133.fits'",
    )
    rng = ctx.rng("fault", idx, cam)
    for t in range(t_full + 30_000, t_purge, 30_000):
        ctx.log(
            t,
            cam,
            "daq",
            "ERROR",
            f"write failed: [Errno 28] No space left on device "
            f"(dropped {rng.randint(15000, 19000)} events)",
        )
    ctx.log(t_purge, cam, "os", "INFO", "cleanup: purged 412 old run files from /data, usage 58%")
    ctx.log(t_purge + 1000, cam, "daq", "INFO", "writer resumed")

    ctx.label(
        fault_index=idx,
        kind="disk_full",
        camera=cam,
        subsystem="os",
        t0=t0,
        t1=t_purge + 1000,
        root_cause="data disk filled to 100%; DAQ writes failed with ENOSPC and the event rate "
        "dropped to zero until the cleanup job freed space",
        expected=[
            ctx.expect("limit", cam, "os", crossing(95), 120, ch),
            ctx.expect("traceback", cam, "daq", t_full, 5),
        ],
        details={
            "full_at": ctx.iso(t_full),
            "purged_at": ctx.iso(t_purge),
            "data_loss_s": (t_purge - t_full) / 1000,
        },
    )


def new_signature(ctx: SimContext, f: NewSignature, idx: int, cam: str, t0: int) -> None:
    step = parse_duration_ms(f.interval)
    for i in range(f.repeats):
        ctx.log(t0 + i * step, cam, f.subsystem, "ERROR", f.text)
    ctx.label(
        fault_index=idx,
        kind="new_signature",
        camera=cam,
        subsystem=f.subsystem,
        t0=t0,
        t1=t0 + (f.repeats - 1) * step,
        root_cause="unknown: first occurrence of a new error template (no runbook entry)",
        expected=[ctx.expect("new_signature", cam, f.subsystem, t0, 5)],
        details={"text": f.text, "repeats": f.repeats},
    )


def prompt_injection(ctx: SimContext, f: PromptInjection, idx: int, cam: str, t0: int) -> None:
    ctx.log(t0, cam, f.subsystem, "WARNING", f.text)
    ctx.label(
        fault_index=idx,
        kind="prompt_injection",
        camera=cam,
        subsystem=f.subsystem,
        t0=t0,
        t1=t0,
        root_cause="untrusted log text containing instructions aimed at an LLM; not an "
        "instrument fault",
        expected=[],
        details={"text": f.text},
    )


def _buffer_traceback(good: int, bad: int) -> str:
    return (
        "Unhandled exception in readout worker\n"
        "Traceback (most recent call last):\n"
        '  File "/opt/cam/readout/worker.py", line 212, in run\n'
        "    self._drain(board)\n"
        '  File "/opt/cam/readout/worker.py", line 148, in _drain\n'
        "    buf.copy_into(self._frame, size=self.cfg.buffer_size)\n"
        '  File "/opt/cam/readout/buffer.py", line 77, in copy_into\n'
        "    raise BufferSizeMismatch(expected=frame.nbytes, got=size)\n"
        f"readout.buffer.BufferSizeMismatch: frame requires {good} bytes, buffer_size={bad}"
    )


Injector = Callable[[SimContext, Any, int, str, int], None]

INJECTORS: dict[str, Injector] = {
    "cooling_drift": cooling_drift,
    "config_reload_crash": config_reload_crash,
    "hv_trip": hv_trip,
    "network_drop": network_drop,
    "disk_full": disk_full,
    "new_signature": new_signature,
    "prompt_injection": prompt_injection,
}
