"""Plausible slow-signal packets for the lab, built with the camera's own packet class.

The shipped mock sends either random words (every sensor-fault bit set at random) or one
constant example packet stamped module slot 1. Neither gives data a detector can learn "normal"
from. This model produces, per TARGET module (TM):

    value = nominal(sensor) + module offset (fixed per TM) + shared ambient wave + noise
            + active faults from the control file

and encodes it with the inverse of the server's own conversions, so the real server decodes,
calibrates and publishes it exactly as it would hardware data. Nominal values are plausible
lab-room numbers, not measured camera values; they are assumptions and are stated as such.

Control file (re-read at most once per second; written by the fault harness):
    /home/sstcam/lab-control/slowsignal.json
    {"mode": "realistic" | "example" | "random",
     "faults": [
        {"type": "drift", "module": 7, "sensors": ["sipm1"], "slope_c_per_h": 0.8, "since": 1790620000.0},
        {"type": "offset", "module": 3, "sensors": ["preamp"], "delta_c": 5.0},
        {"type": "sensor_fault", "module": 12, "sensors": ["sipm2"], "bits": 128},
        {"type": "dead", "module": 5}
     ]}
Sensor names may be globbed ('sipm*', '*').
"""

import fnmatch
import json
import math
import os
import random
import time
from pathlib import Path
from typing import Any

CONTROL = Path(os.environ.get("LAB_CONTROL_DIR", "/home/sstcam/lab-control")) / "slowsignal.json"

# °C. SPI RTD sensors (per TM), then I2C board sensors.
SPI_NOMINAL = {
    "prim_asics": 32.0, "aux_asics": 31.5, "prim_shaper": 29.0, "aux_shaper": 28.5,
    "sipm1": 24.0, "sipm2": 24.2, "sipm3": 23.9, "sipm4": 24.1, "preamp": 33.0,
}
I2C_NOMINAL = {"power": 35.0, "aux": 30.0, "primary": 31.0}
HV_VOLTAGE_V, HV_CURRENT_A = 12.0, 0.020

MODULE_SPREAD_C = 0.6  # sd of the fixed per-module, per-sensor offset
AMBIENT_AMP_C, AMBIENT_PERIOD_S = 0.4, 3 * 3600  # shared slow variation
NOISE_C = 0.03


# --- encoders: inverses of sstcam_slowsignal.utils.conversions -------------------------------


def spi_raw(temp_c: float, fault_bits: int = 0) -> int:
    """SPI RTD word: 24-bit value in 1/1024 °C, fault bits in the top byte."""
    return ((fault_bits & 0xFF) << 24) | (max(0, round(temp_c * 1024)) & 0xFFFFFF)


def i2c_pow_raw(temp_c: float) -> int:
    """Power-board sensor: 8-bit magnitude in 0.5 °C split as ((raw & 0x7F) << 1) + bit 15,
    sign in bit 7."""
    n = min(abs(round(temp_c / 0.5)), 0xFF)
    raw = ((n >> 1) & 0x7F) | ((n & 1) << 15)
    return raw | (0x80 if temp_c < 0 else 0)


def i2c_pa_raw(temp_c: float) -> int:
    """Aux/primary sensors: byte-swapped 16-bit word; value >> 3 in 1/32 °C; sign in bit 15."""
    n = min(abs(round(temp_c / 0.03125)), 0x0FFF)
    word = (n << 3) | (0x8000 if temp_c < 0 else 0)
    return ((word & 0xFF) << 8) | (word >> 8)


def hv_raw(value: float, lsb: float) -> int:
    """12-bit HV reading split as: high 8 bits in the low byte, low 4 bits in the top nibble."""
    n = min(max(round(value / lsb), 0), 0xFFF)
    return ((n >> 4) & 0xFF) | ((n & 0xF) << 12)


# --- control file --------------------------------------------------------------------------


class Control:
    def __init__(self, path: Path = CONTROL, default_mode: str = "realistic"):
        self.path, self.default_mode = path, default_mode
        self._mtime: float | None = None
        self._checked = 0.0
        self.mode, self.faults = default_mode, []  # type: str, list[dict[str, Any]]

    def refresh(self) -> None:
        now = time.monotonic()
        if now - self._checked < 1.0:
            return
        self._checked = now
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            self.mode, self.faults, self._mtime = self.default_mode, [], None
            return
        if mtime == self._mtime:
            return
        try:
            data = json.loads(self.path.read_text() or "{}")
        except (OSError, json.JSONDecodeError):
            return  # half-written file: keep the previous state, retry next second
        self._mtime = mtime
        self.mode = data.get("mode", self.default_mode)
        self.faults = list(data.get("faults", []))

    def for_module(self, tm: int) -> list[dict[str, Any]]:
        return [f for f in self.faults if int(f.get("module", -1)) == tm]


def _applies(fault: dict[str, Any], sensor: str) -> bool:
    return any(fnmatch.fnmatch(sensor, pat) for pat in fault.get("sensors", ["*"]))


# --- the model -----------------------------------------------------------------------------


class ModuleModel:
    def __init__(self, tm: int, control: Control):
        self.tm, self.control = tm, control
        rng = random.Random(f"tm-offsets:{tm}")
        self.offsets = {s: rng.gauss(0.0, MODULE_SPREAD_C) for s in (*SPI_NOMINAL, *I2C_NOMINAL)}
        self.noise = random.Random()

    def temperature(self, sensor: str, nominal: float, now: float,
                    faults: list[dict[str, Any]]) -> float:
        t = nominal + self.offsets[sensor]
        t += AMBIENT_AMP_C * math.sin(2 * math.pi * now / AMBIENT_PERIOD_S)
        t += self.noise.gauss(0.0, NOISE_C)
        for f in faults:
            if not _applies(f, sensor):
                continue
            if f["type"] == "drift":
                t += float(f["slope_c_per_h"]) * max(0.0, now - float(f["since"])) / 3600
            elif f["type"] == "offset":
                t += float(f["delta_c"])
        return t

    def is_dead(self) -> bool:
        self.control.refresh()
        return any(f["type"] == "dead" for f in self.control.for_module(self.tm))

    def fill(self, pkt: Any) -> Any:
        """Overwrite the physical fields of an example packet (the camera's own class)."""
        now = time.time()
        faults = self.control.for_module(self.tm)
        pkt.tm_slot = self.tm
        pkt.tm_index = self.tm
        for sensor, nominal in SPI_NOMINAL.items():
            bits = 0
            for f in faults:
                if f["type"] == "sensor_fault" and _applies(f, sensor):
                    bits |= int(f.get("bits", 0x80))
            setattr(pkt, f"spi_temp_{sensor}", spi_raw(self.temperature(sensor, nominal, now, faults), bits))
        pkt.i2c_power_board_temperature = i2c_pow_raw(
            self.temperature("power", I2C_NOMINAL["power"], now, faults))
        pkt.i2c_aux_board_temperature = i2c_pa_raw(
            self.temperature("aux", I2C_NOMINAL["aux"], now, faults))
        pkt.i2c_primary_board_temperature = i2c_pa_raw(
            self.temperature("primary", I2C_NOMINAL["primary"], now, faults))
        pkt.hv_input_voltage = hv_raw(HV_VOLTAGE_V + self.noise.gauss(0, 0.01), 0.025)
        pkt.hv_input_current = hv_raw(HV_CURRENT_A + self.noise.gauss(0, 0.0002), 200e-6)
        return pkt
