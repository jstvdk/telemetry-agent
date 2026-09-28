"""Patch the packaged LOCAL_DB configuration so one camera server runs on mocks in a box.

Only the keys listed here change; everything else stays as shipped, so the servers behave
as they would on a lab machine. Run at image build time: patch_config.py /etc/sstcam
"""

import sys
from pathlib import Path

import yaml

SERVER_ID = 0

SERVER = {
    # logs: plain text everywhere, every sink on (terminal -> journal, per-process files,
    # socket -> gatherer -> central file)
    "log_to_terminal": True,
    "log_to_terminal_colour": False,
    "log_to_local_file": True,
    "log_to_local_file_colour": False,
    "log_to_socket": True,
    "log_to_central_file": True,
    # no external services inside the box
    "gatherer_to_influxdb": False,
    "gatherer_influxdb_token": "",
    "gatherer_from_telescope_influxdb": False,
    "gatherer_from_weatherstation_influxdb": False,
    # everything local
    "grpc_host": "localhost",
    "zmq_host": "localhost",
}

UNIT = {
    "controller_adapter": "SIMULATION",
    "backplane_connection": "DISCONNECTED",
}


def patch(path: Path, changes: dict[str, object]) -> None:
    data = yaml.safe_load(path.read_text())
    before = {k: data.get(k, "<absent>") for k in changes}
    data.update(changes)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    for k, v in changes.items():
        if before[k] != v:
            old = "<redacted>" if "token" in k else repr(before[k])
            print(f"{path.name}: {k}: {old} -> {v!r}")


def main(root: str) -> None:
    cfg = Path(root)
    server = cfg / f"sst.camera.server.{SERVER_ID}.yaml"
    patch(server, SERVER)
    unit_id = yaml.safe_load(server.read_text())["unit_id"]
    patch(cfg / f"sst.camera.unit.{unit_id}.yaml", UNIT)


if __name__ == "__main__":
    main(sys.argv[1])
