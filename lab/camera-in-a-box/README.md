# camera-in-a-box

One camera server in a container: **AlmaLinux 9** (the production OS) with **systemd as PID 1**, running the camera-server orchestrator's own user units unchanged. Hardware is replaced by the software mocks the camera server ships with. The logs, journal entries and monitoring files it produces come from the real code paths; this is tier B in [PROVENANCE P-08](../../docs/PROVENANCE.md#p-08--real-camera-server-observability).

```
container "cam-01"  (AlmaLinux 9, systemd PID 1, journald persistent)
└── user@1000 (sstcam, lingering)  ── sstcam.target
    ├── sstcam-session        oneshot: /data/SSTCAM/<session> + current symlink
    ├── sstcam-gatherer       real   — collects monitoring + socket logs → central log
    ├── sstcam-chiller        --mock (Modbus simulator)          ┐
    ├── sstcam-slowboard      --mock (TCP protocol mock)         │ drop-ins:
    ├── sstcam-slowsignal     --mock via lab launcher            │ systemd/user/*.d/mock.conf
    ├── sstcam-eventbuilder   real C++ core, fed by ↓            ┘
    ├── sstcam-eventbuilder-mock   `eventbuilder mock start empty`   (extra unit)
    ├── sstcam-controller     --simulated (FSM adapter)             (extra unit)
    ├── sstcam-connect        once at boot: chiller/slowboard `connect` (extra unit)
    ├── sstcam-target / -pointing   upstream units, no mock (pointing Requires= slowsignal)
    └── sstcam-backplane      masked: first camera version has no backplane
```

## Use

```bash
make build      # stage sources into .build/ and build the image (first build ~10 min)
make run        # start cam-01
make status     # unit states
make logs       # follow the whole journal
make shell      # bash as the camera user, sstcam CLI on PATH
make stop

./capture.sh baseline-30m   # → captures/baseline-30m/ (git-ignored): data/, journal.jsonl,
                            #   monitoring.jsonl (decoded), units.txt, manifest.json
```

Sources come from local checkouts (override with `SSTCAM_SERVER_SRC=… CAMBRIDGE_SRC=… make build`). `stage.sh` copies them without `.git` and build artifacts into `.build/`, which is git-ignored; the image labels record the exact revisions:

```bash
docker inspect camera-in-a-box:dev --format '{{json .Config.Labels}}'
```

## What differs from a lab machine, and why

| Difference | Reason |
|---|---|
| `--mock` / `--simulated` via drop-ins; extra units for controller and eventbuilder mock | No hardware. Upstream unit files are copied unchanged. |
| `%h/miniforge3/envs/sstcam` is a symlink to the uv venv | Upstream units hard-code that path. |
| Config: `LOCAL_DB` from the source tree, patched by `config/patch_config.py` | Colour off, local files on, InfluxDB off (and token removed), simulation adapter. Every change is printed at build time. |
| `--privileged --cgroupns=host` | systemd needs to manage cgroups inside the container. It also enables network and resource fault injection. |
| slowsignal launcher (`lab/sstcam_lab.py`) with `LAB_SLOWSIGNAL_PACKETS=example` | The mock's default random packets set random sensor-fault bits: ~235 multi-line WARNINGs/s. `random` is kept as a fault to inject. |
| Combined slow-signal calibration CSV rebuilt from per-slot files (`config/merge_slowsignal_calib.py`) | The staged branch removed it while the loader still needs it; slowsignal would crash-loop. |
| Built with `-fsigned-char`; `GIT_LFS_SKIP_SMUDGE=1` | Upstream arm64 `char`/`getopt` bug under `-Werror`; a missing LFS object in a dependency's remote. |

Each workaround and each finding about the real system is recorded in [PROVENANCE P-09](../../docs/PROVENANCE.md#p-09--camera-in-a-box-tier-b-infrastructure).

## Output of one camera

| Path (in the box) | Content |
|---|---|
| `/data/SSTCAM/logs/log_<start>_<process>.txt` | per-process log, pipe format, `yy-mm-dd HH:MM:SS`, new file per process start |
| `/data/SSTCAM/logs/sstcam-server_<date>.log` | central log from the gatherer, ICD format with ms |
| `/data/SSTCAM/logs/config_<start>.yml` | config snapshot at gatherer start |
| `/data/SSTCAM/monitoring/monitoring_<date>.bin` | gatherer monitoring, length-prefixed protobuf (decode: `lab/export_monitoring.py`) |
| `/data/SSTCAM/slowsignal/slowsignal_<date>.bin` | slow-signal stream |
| journal (`journalctl -o json`) | unit starts/stops/exits/restarts + service stdout |

## Faults and labels

```bash
uv run shiftassist-lab --container cam-02 check                       # healthy?
uv run shiftassist-lab --container cam-02 run scenarios/B01-first-faults.yaml --dry-run
uv run shiftassist-lab --container cam-02 run scenarios/B01-first-faults.yaml
uv run shiftassist-lab --container cam-02 reset                       # undo anything, any state
uv run shiftassist-collect verify-labels captures/B01-…               # is each label's evidence there?
uv run shiftassist-collect verify-labels captures/B00-… --labels-from captures/B01-…   # negative control
```

A run writes `captures/<scenario>-<time>/`: `labels.jsonl` (ground truth, container clock), `harness.jsonl` (every command with time and exit code), `run.json`, and the capture (`data/`, `journal.jsonl`, `monitoring.jsonl`).

Fault types (`src/shiftassist/lab/faults.py`): `process_crash`, `process_hang`, `gatherer_down`, `calibration_missing`, `disk_full` (only on a small tmpfs `/data`), `slowsignal_drift`, `sensor_fault`, `module_dead`, `chiller_ramp`. Each is reverted in `finally`; if a revert fails the harness resets everything; if the camera does not recover, the run stops.
