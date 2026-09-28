"""Run the `sstcam` CLI with lab-only switches applied first. The camera source is not modified.

    LAB_SLOWSIGNAL_PACKETS=example   well-formed packets from the slow-signal mock (default)
    LAB_SLOWSIGNAL_PACKETS=random    the mock's own default: random words, so random sensor
                                     fault bits -> a flood of multi-line hardware WARNINGs
                                     (used as the injected fault "temperature sensor fault flood")

Usage (same arguments as `sstcam`):  python -m sstcam_lab slowsignal serve --mock
"""

import os
import sys


def _apply() -> None:
    mode = os.environ.get("LAB_SLOWSIGNAL_PACKETS", "example")
    if mode == "example":
        from sstcam_slowsignal.mock.target import MockTARGET

        original = MockTARGET.generate_packet

        def generate_packet(self, seed=None, example=True):  # type: ignore[no-untyped-def]
            return original(self, seed=seed, example=example)

        MockTARGET.generate_packet = generate_packet  # type: ignore[method-assign]
    elif mode != "random":
        raise SystemExit(f"LAB_SLOWSIGNAL_PACKETS must be 'example' or 'random', got {mode!r}")


if __name__ == "__main__":
    _apply()
    from sstcam_cli.cli import cli

    sys.argv[0] = "sstcam"
    cli()
