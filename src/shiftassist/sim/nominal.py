"""Nominal camera behaviour: telemetry channel models and background log chatter.

The background deliberately contains 'trap' lines (``error_count=0``, ``NO_ERROR``) and
harmless WARNINGs, so that substring matching on words like ERROR gives wrong counts
(v0 finding F1) and so that detection has something to *not* alarm on.
"""

import math
import random
from dataclasses import dataclass

SUBSYSTEMS = ("readout", "cooling", "hv", "daq", "config", "os")


@dataclass(frozen=True, slots=True)
class ChannelModel:
    nominal: float
    noise: float  # Gaussian sigma
    wave_amp: float = 0.0  # slow sinusoidal variation
    wave_period_s: float = 3600.0
    drift_per_h: float = 0.0  # slow nominal drift (e.g. disk usage)
    decimals: int = 3


CHANNELS: dict[str, ChannelModel] = {
    "cooling.plate_temp_c": ChannelModel(15.0, 0.03, wave_amp=0.08, wave_period_s=5400),
    "cooling.coolant_flow_lpm": ChannelModel(4.0, 0.02),
    "hv.voltage_v": ChannelModel(1100.0, 0.4, decimals=1),
    "hv.current_ua": ChannelModel(80.0, 1.2, wave_amp=2.0, wave_period_s=7200, decimals=2),
    "readout.trigger_rate_hz": ChannelModel(600.0, 12.0, decimals=1),
    "daq.event_rate_hz": ChannelModel(590.0, 12.0, decimals=1),
    "os.disk_used_pct": ChannelModel(42.0, 0.0, drift_per_h=0.2, decimals=2),
    "os.cpu_pct": ChannelModel(35.0, 4.0, decimals=1),
}

CONFIG_PATH = "/opt/cam/config/readout.yaml"
GOOD_CONFIG_HASH = "a1b2c3d"


def nominal_series(model: ChannelModel, grid_ms: list[int], rng: random.Random) -> list[float]:
    phase = rng.uniform(0, 2 * math.pi)
    out = []
    for t in grid_ms:
        h = t / 3_600_000
        v = model.nominal + model.drift_per_h * h
        if model.wave_amp:
            v += model.wave_amp * math.sin(2 * math.pi * t / 1000 / model.wave_period_s + phase)
        if model.noise:
            v += rng.gauss(0.0, model.noise)
        out.append(v)
    return out


BENIGN_WARNINGS = (
    ("cooling", "sensor bus slow response ({ms} ms), retry ok"),
    ("os", "ntp offset {off:+.1f} ms above soft threshold, still within tolerance"),
    ("daq", "event builder queue {q}% full, draining"),
)
