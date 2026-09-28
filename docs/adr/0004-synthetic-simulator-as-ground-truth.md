# ADR-0004 · In-repo simulator with fault scenarios as the source of ground truth

**Status:** Accepted

## Context
v0 subscribed to an external mock-monitoring stream that is not part of this repo. As a result:
- nobody else can run the project;
- there is no ground truth, so expected answers are filled in by hand from SQL queries on a snapshot;
- incidents happen by chance, not by design, so specific failure types cannot be tested.

Real instrument data and code cannot be put in a public repo.

## Decision
Build a small **camera simulator** in the repo:
- **Scenario = YAML file**: duration, cameras, seed, baseline behaviour, and a list of injected faults with times.
- The simulator emits log lines (including multi-line tracebacks and benign "trap" lines such as `error_count=0`) and telemetry, on **ZMQ PUB** (same interface as v0) or straight into a snapshot file for fast evaluation runs.
- Every injected fault writes a **label**: kind, camera, subsystem, start/end, root cause, the events detection must produce, and the evidence a correct explanation must cite.
- Deterministic given the seed. Time is simulated and can be accelerated.

Initial scenario set:

| ID | Scenario | What it tests |
|---|---|---|
| S01 | Nominal night | False alerts; "nothing is wrong" answers |
| S02 | Slow cooling drift (0.8 °C/h) | Trend detection; features instead of raw data |
| S03 | Config reload → readout traceback → restart, plus an unrelated temperature wiggle | Causal explanation (UC-01); ignoring a distractor |
| S04 | HV channel trip and recovery | Limit rule with hysteresis; counting |
| S05 | Network drop: heartbeats stop across subsystems | Gap detection; common cause |
| S06 | Disk fills up → write errors | Multi-step causal chain |
| S07 | Never-seen error template | New-signature detection |
| S08 | Benign noise with `NO_ERROR` / `error_count=0` | Substring traps from v0 |
| S09 | Same fault on 3 cameras within 30 s | Array-level correlation |
| S10 | Log line containing an injected instruction | Prompt-injection robustness |

## Consequences
- `make demo` works on any laptop. Ground truth is exact and free.
- **Risk: the simulator is too clean.** Real logs are messier. Mitigations: noise and trap lines in every scenario; perturbations (reordered lines, clock skew, broken tracebacks); later, replay of real recorded logs in a private setting, using the same label format.
- Scenario YAML is also the format for real incidents later, so the eval harness does not change.

## Alternatives rejected
- **Keep the external stream:** not reproducible, no labels.
- **LLM-generated synthetic logs:** not deterministic, and the labels would be only as good as the generator.
