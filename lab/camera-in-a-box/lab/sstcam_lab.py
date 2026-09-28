"""Run the `sstcam` CLI with lab-only switches applied first. The camera source is not modified.

Slow-signal mock packet mode (env LAB_SLOWSIGNAL_PACKETS = default; the control file overrides it
at runtime, see slowsignal_model.py):
    realistic  per-module plausible values from slowsignal_model (default), with injectable faults
    example    the mock's constant example packet (all modules claim slot 1)
    random     the mock's own default: random words -> random sensor-fault bits -> WARNING flood

Usage (same arguments as `sstcam`):  python sstcam_lab.py slowsignal serve --mock
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _apply() -> None:
    from sstcam_slowsignal.mock.target import MockTARGET
    from sstcam_slowsignal.packet import SlowSignalPacket
    from sstcam_telecom.udp.client import UDPClient

    from slowsignal_model import Control, ModuleModel

    default = os.environ.get("LAB_SLOWSIGNAL_PACKETS", "realistic")
    if default not in ("realistic", "example", "random"):
        raise SystemExit(f"LAB_SLOWSIGNAL_PACKETS must be realistic|example|random, got {default!r}")
    control = Control(default_mode=default)
    models: dict[int, ModuleModel] = {}
    original = MockTARGET.generate_packet

    def generate_packet(self, seed=None, example=False):  # type: ignore[no-untyped-def]
        control.refresh()
        tm = int(self._tm_id)
        model = models.setdefault(tm, ModuleModel(tm, control))
        if model.is_dead():
            return bytearray()  # dropped by the patched send below: the module is silent
        if control.mode == "random":
            return original(self, seed=seed, example=False)
        if control.mode == "example":
            return original(self, seed=seed, example=True)
        return model.fill(SlowSignalPacket.from_example(tm_id=tm)).__bytes__()

    MockTARGET.generate_packet = generate_packet  # type: ignore[method-assign]

    send = UDPClient.send

    async def send_unless_empty(self, data):  # type: ignore[no-untyped-def]
        if len(data) == 0:
            return None
        return await send(self, data)

    UDPClient.send = send_unless_empty  # type: ignore[method-assign]


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "slowsignal":
        _apply()
    from sstcam_cli.cli import cli

    sys.argv[0] = "sstcam"
    cli()
