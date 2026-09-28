# Provenance

A dated record of how this project was built: every step, the decisions taken at each one, and the things that went wrong. It is updated as work happens, not rewritten afterwards. [00 · Journey](00-journey.md) tells the story; this file is the evidence behind it.

**Conventions**
- Entries are append-only. A reversed decision gets a new entry that refers to the old one.
- **D-** = decision, **X-** = failure or dead end, **→ ADR** = where the decision is written up in full.
- *Evidence* points at something checkable: a commit, a file, a test, or a command with its output.

---

## Timeline

| Entry | Date | Step | Outcome | Commit / tag |
|---|---|---|---|---|
| [P-00](#p-00--brainstorm) | before 2026-09-25 | Brainstorm | Wish list; core use case found | — (private notes) |
| [P-01](#p-01--structured-roadmap) | ≤ 2026-09-25 | Structured roadmap | Principles, layers, scope cuts | — (private notes) |
| [P-02](#p-02--learning-spike-plan) | 2026-09-27 | Learning-spike plan | Two-evening plan to learn the mechanics | — (private notes) |
| [P-03](#p-03--learning-spike-v0) | 2026-09-27 | Learning spike (v0) | Working loop + MCP; naive by design | `v0-spike` |
| [P-04](#p-04--spike-review) | 2026-09-28 | Spike review | 17 findings, 3 high severity, measured | docs commit |
| [P-05](#p-05--design-documentation) | 2026-09-28 | Design docs | Rationale, requirements, architecture, 8 ADRs, eval + test plan | docs commit |
| [P-06](#p-06--repository-foundations-m0) | 2026-09-28 | M0 repo foundations | git, packaging, baseline/, CI | M0 commit |
| [P-07](#p-07--simulator-m1) | 2026-09-28 | M1 simulator | Seeded scenarios with ground-truth labels; v0 counter says 112 errors on a night with 0 | M1 commit |
| [P-08](#p-08--real-camera-server-observability) | 2026-09-28 | Real observability summary | Invented format found; three data tiers proposed | — |
| [P-09](#p-09--camera-in-a-box-tier-b-infrastructure) | 2026-09-28 | camera-in-a-box | Real camera software on mocks under systemd; 9 findings about the real system, 3 upstream build bugs | lab commit |

---

## P-00 · Brainstorm

**Goal.** Write down what an operator assistant for a telescope camera could do.

**Done.** A free-form list: scan all subsystems, detect violations and trends, propose fixes (code fix, reload, config change), write shift logs; six or more specialised agents; cover the camera, telescope structure, weather, pointing and transient-alert scheduling.

**Decisions**
- **D-00a** The operator always takes the final decision. This was the first line of the notes and has held since.
- **D-00b** The first real use case is **explaining a failure before data taking**, using the team's past incidents and code. It came from the operator's own experience: read the traceback, paste it into a generic chatbot, search, ask an expert.
- **D-00c** Defer telescope structure monitoring and transient alerts/scheduling: other teams own them.

**Failures / dead ends**
- **X-00a Over-scoped.** Actions on hardware and software, six agents, five external systems. None of it came with a way to test whether it worked. Fixed in P-01.

**Evidence.** Private notebook (not published: contains institutional details).

---

## P-01 · Structured roadmap

**Goal.** Turn the wish list into something buildable and defensible.

**Method.** One question asked of every brainstorm item: *does this need a guarantee, or does it need language?*

**Decisions**
- **D-01a** Read-only by construction; mitigations as text only. → [ADR-0001](adr/0001-read-only-by-construction.md)
- **D-01b** Detection is deterministic; the LLM explains, correlates and writes. → [ADR-0002](adr/0002-deterministic-detection-llm-for-language.md)
- **D-01c** Six agents collapsed to one agent loop plus fixed pipelines. → [ADR-0003](adr/0003-pipelines-first-one-agent-loop.md)
- **D-01d** No model training; knowledge lives in reviewable files (runbook with `verified` / `ai-draft` status, incident library).
- **D-01e** Every claim must cite evidence, and code checks it. → [ADR-0005](adr/0005-grounding-validator.md)
- **D-01f** Model-agnostic; must run on a local open-weight model on site. → [ADR-0007](adr/0007-model-agnostic-provider-interface.md)
- **D-01g** The labelled incident library, not any model, is the long-lived asset.
- **D-01h** Fallback: if the LLM layer slips, detection plus an auto-generated shift log is still useful.

**Failures / dead ends**
- **X-01a No hands-on experience yet** with tool calling, MCP or token costs, so the roadmap's cost and effort estimates were guesses. This is why P-02 exists.

**Evidence.** Private roadmap (same reason). Its public content is in [01](01-rationale.md), [02](02-requirements.md) and [03](03-architecture.md).

---

## P-02 · Learning-spike plan

**Goal.** Learn the mechanics before building the real thing: tool calling, the agent loop, MCP, and token and cost measurement. Time box: two evenings.

**Decisions**
- **D-02a** Build the agent loop **without a framework**, to see what frameworks hide.
- **D-02b** Collector + SQLite instead of reading the stream directly: an agent needs history.
- **D-02c** "Now" = newest stored record, so a frozen snapshot gives reproducible answers.
- **D-02d** Cap tool output (characters per message, messages per call, characters per result): tool output is resent as input tokens at every step.
- **D-02e** Only mock data and own code in the repo.

**Failures / dead ends.** None at planning time. The plan knowingly accepted a naive tool design (raw text, keyword counts) to keep it to two evenings.

---

## P-03 · Learning spike (v0)

**Goal.** Execute P-02.

**Done.** `collector.py`, `tools.py`, `server.py` (MCP), `agent.py` (loop + usage log), `eval.py`, `analyze.py`, `questions.jsonl` (2 placeholder items). Used from the Claude desktop app over MCP and from the CLI agent.

**Learned**
- The whole agent is ~30 lines: call model → run requested tools → append results → repeat.
- Input tokens grow at every step because the full context is resent. Output caps are the main cost lever.
- MCP separates tools from clients: the same functions worked in the desktop app and in the hand-written loop.

**Failures / dead ends** (found in P-04, listed here because this is where they were introduced)
- **X-03a** Keyword counting over raw text gives wrong numbers (F1).
- **X-03b** The spike depends on an external mock stream that is not in the repo, and the question set has no real expected answers, so nobody else can run or score it (F2, F3).
- **X-03c** Tool definitions are written three times and already differ (F7).

**Evidence.** Tag `v0-spike`: code committed unchanged before any refactor.

---

## P-04 · Spike review

**Goal.** Judge v0 against the roadmap's own principles before building on it.

**Method.** Read every file; reproduce suspected defects in a scratch environment instead of guessing; check the MCP API against the installed SDK version.

**Findings.** 17 in total, 3 high severity; full table in [06](06-v0-spike-review.md). Measured:

| Check | Command / setup | Result |
|---|---|---|
| Keyword count | 4-row DB: `error_count=0`, `ERROR buffer overflow`, `NO_ERROR flag set`, `WARNING …`; `tools.count_keywords()` | `{'ERROR': 3, 'WARN': 1}`; truth is 1 and 1 |
| Missing DB | `tools.list_topics()` with no DB file | `OperationalError: no such table: messages`, and an empty `telemetry.db` is created as a side effect |
| Result truncation | `json.loads(json.dumps(big)[:8000])` | `JSONDecodeError`: the model receives invalid JSON |
| MCP API | `from mcp.server.mcpserver import MCPServer` on `mcp` 2.2.0 | Works. `FastMCP` import fails on 2.x; v0 was already correct |

**Decisions**
- **D-04a Keep v0 as the baseline** for experiment E1 instead of deleting it. The comparison *naive tools vs. structured events on the same model* is the most informative experiment available.
- **D-04b Build a vertical slice next** (thin version of every layer) rather than deepening any single layer.
- **D-04c Replace the external stream with an in-repo simulator** that writes its own ground truth. → [ADR-0004](adr/0004-synthetic-simulator-as-ground-truth.md)

**Failures / dead ends**
- **X-04a** The spike's eval could never have produced trustworthy numbers: manual scoring, one trial per question, prices unset (cost always NaN). Caught before any model comparison was reported.

---

## P-05 · Design documentation

**Goal.** Write down the design *before* the v1 code, so each piece of code implements a decision that is already on record.

**Done.** [01 rationale](01-rationale.md), [02 requirements](02-requirements.md) (7 use cases, FR/NFR, acceptance criteria), [03 architecture](03-architecture.md) (data model, tool contract, answer schema, sequence), [8 ADRs](adr/README.md), [04 evaluation](04-evaluation.md) (6 metric layers, 5 experiments, statistics), [05 test plan](05-test-plan.md) (~40 test cases), [07 delivery plan](07-delivery-plan.md).

**Decisions**
- **D-05a Single tool registry** generates MCP and agent schemas. → [ADR-0006](adr/0006-single-tool-registry-mcp.md)
- **D-05b Structured final answer** via a `submit_answer` tool, so answers are machine-checkable.
- **D-05c Headline reliability metric is pass^k** (right in all k runs), not pass@1. An operator needs consistency.
- **D-05d The LLM judge is calibrated** against 30 hand-scored answers before its scores are used (κ ≥ 0.6).
- **D-05e Accuracy targets are set after the first baseline run**, not guessed in advance. Only detection and grounding have fixed targets, because they are guaranteed by construction.
- **D-05f Private notes stay private.** `internal_docs/` is git-ignored. Public docs contain no institution names, colleagues, policy or funding details.
- **D-05g Status markers** (✅ / 🔨 / 📐) on every component, so no document claims something works before it does.

**Failures / dead ends.** None yet. Risk noted: the docs describe a system that does not exist yet. Mitigation: D-05g, and the status markers are updated in the same commit as the code.

---

## P-06 · Repository foundations (M0)

**Goal.** A repo that anyone can clone, install and test with one command.

**Decisions**
- **D-06a Commit v0 unchanged first, then tag it** (`v0-spike`), then refactor. The history shows the real starting point.
- **D-06b Repo-local git identity** (personal address) for this project, separate from work identity.
- **D-06c uv + `pyproject.toml`, Python 3.12**, `src/` layout. 3.12 rather than the machine's 3.14: wide wheel availability for `pyzmq` and scientific packages, and pinned by uv, so it doesn't depend on the host Python.
- **D-06d v0 moves to `baseline/`** unchanged apart from the move; runnable as before.

**Failures / dead ends.** None.

**Evidence.** Commit `build: M0 foundations`; `uv sync` resolves on Python 3.12.8; `make test` runs in CI.

---

## P-07 · Simulator (M1)

**Goal.** Seeded scenarios that generate logs and telemetry with ground-truth labels, on the same ZMQ interface v0 used.

**Done.** `src/shiftassist/sim/`: pydantic scenario model with one class per fault kind (unknown kinds and misspelled parameters fail at load time); a generator with integer-millisecond simulated time and an independent seeded RNG per component; seven fault injectors that each write their own label; JSONL output + manifest with SHA-256; ZMQ publisher; CLI. Scenarios S01–S10. 63 tests.

**Decisions**
- **D-07a Ground truth comes from the injector, not from analysing the output.** Each injector writes the label for exactly what it changed, including the detection events it expects (`kind`, `subsystem`, `near`, `tolerance_s`).
- **D-07b Expected events are described by kind, camera and time, not by event ID**, so labels stay valid when the detector changes.
- **D-07c Fault log lines are never suppressed by blackouts; nominal lines are.** Without this, a network drop would delete the crash traceback that explains it.
- **D-07d Trap lines are part of the nominal background** (`error_count=0`, `NO_ERROR`, `ERROR_LATCH clear`), so every scenario tests against the v0 failure mode.
- **D-07e Distractors get labels too** (`kind: distractor`, no expected events), so the eval can ask "did X cause Y?" and score a *no*.
- **D-07f Labels hold the whole common-cause group** (`group` field), so S09 can score array-level correlation.

**Failures / dead ends**
- **X-07a The first HV-trip ramp never crossed the limit in telemetry.** The ramp peaked exactly at the trip time, but the last 10 s sample before it only reached ~140 µA < 150 µA. Found by reasoning about the sampling grid while writing the test. Fixed by peaking one sample earlier; `test_hv_trips` now asserts that telemetry actually crosses the limit.
- **X-07b The simulator's log format and transport were invented, not taken from the real system.** It was built as a single ZMQ stream of `ts LEVEL camera subsystem: text` lines. The real camera server writes per-process log files in a pipe-separated format, a central log in an ICD-defined format, systemd journal entries for restarts, and binary protobuf monitoring (P-08). Found by domain input *after* M1 was built. **Lesson: ask for the real output format before building a simulator of it.** Impact is limited: scenarios, injectors and labels are independent of the rendering, which is the part that changes.

**Evidence** (all reproducible with `make sim SCENARIO=…`)

| Check | Result |
|---|---|
| Same seed, two runs (S03) | byte-identical `stream.jsonl`, `labels.jsonl`, `manifest.json` |
| S03 at 01:50 / 02:13 | config reload `buffer_size=4096 (was 8192)` → traceback `BufferSizeMismatch` at 02:13:00 → exit 02:13:01 → supervisor restart 02:13:40; trigger rate 0 only during 02:13:00–02:13:30 |
| S02 plate temperature slope (least squares after drift start) | 0.8 ± 0.05 °C/h |
| **v0 `count_keywords` fed the simulated stream through the v0 collector logic** | **S01: ERROR = 112, true ERROR/CRITICAL lines = 0.** S08: 88 vs. 0. S04: 86 vs. 2 |

The last row is the strongest evidence for [ADR-0002](adr/0002-deterministic-detection-llm-for-language.md): on a completely healthy night, the v0 tool tells the model there were 112 errors.

---

## P-08 · Real camera-server observability

**Goal.** Replace invented formats with the real ones (X-07b), without putting institutional code or details in the public repo.

**Input.** A private summary of how the real camera-server software logs and monitors, and which subsystems have mocks (kept in `internal_docs/`, git-ignored). The summary was produced by an automated read-only pass and is marked by its author as not line-by-line verified.

**What changes (public-safe summary)**
- Logs are **plain text in several places**: per-process files, a central consolidated file with a standard-defined format, and the systemd journal (process restarts via `Restart=on-failure`). The collector must **tail files and the journal**, not only subscribe to a stream.
- Monitoring is **binary protobuf in daily-rotated files**, optionally mirrored to a time-series DB. The collector needs a monitoring adapter.
- There are **no correlation IDs**. Linking events across processes must use time, process name and logger context, and that is a job for the timeline and the LLM layer.
- Several subsystems have **working mocks with override hooks** (e.g. setting a reported temperature). Faults can therefore be injected into the *real* software, which then writes its *real* log lines. That is more realistic than any synthetic template.
- Some subsystems have **no mock at all**. Faults there can only come from recorded real incidents or synthetic templates.

**Decisions** *(proposed, pending the author's confirmation)*
- **D-08a Three data tiers with one label format:** (A) fully synthetic, public, CI; (B) live fault injection against the real mock stack on a lab machine, private; (C) replay + splice of tier-B recordings, private, for volume and variation. The eval harness does not change between tiers.
- **D-08b Rendering becomes a pluggable dialect.** The public repo ships the generic dialect; the lab dialect lives outside the public repo.
- **D-08c The real source code is not read** by the assistant until the data-policy question on that has an answer. Formats are taken from captured **output** (log files, journal export) instead.
- **D-08d (2026-09-28, author) — reverses D-08c.** This is a study project, so any data may be used, including the real camera-server source and internal data. The log format is generic enough to live in the repo, and the repo can be made private if needed. The public/private split is kept only where it costs nothing (`internal_docs/` stays git-ignored).
- **D-08e (author)** Aim for large volumes of data generated over time by the simulators, including **system-wide** injected faults, not only per-subsystem ones.

**Findings while checking where tier B can run**
- The production target is Linux (AlmaLinux 9) with services supervised as systemd user units (`Restart=on-failure`, one target unit for the whole suite) and logs in the journal. macOS has neither systemd nor journald.
- The repo's systemd Dockerfile is **truncated**: it ends in the middle of a `RUN … &&` command, so it cannot build as-is. The prebuilt images sit in an authenticated registry. A tier-B image has to be built here.
- Docker (linux/arm64) is available on the development Mac.

---

## P-09 · camera-in-a-box (tier B infrastructure)

**Goal.** Run the real camera-server software, unmodified, on mocks in a disposable Linux box on the development Mac, with the production OS and supervision model, and capture a clean baseline.

**Done.** `lab/camera-in-a-box/`: AlmaLinux 9 image with systemd as PID 1; the orchestrator's upstream user units run unchanged under a lingering user manager; hardware replaced by the project's own mocks through systemd drop-ins; config patched by a script that prints every change. Sources staged from local checkouts, with revisions recorded in image labels. `capture.sh` exports logs, journal, decoded monitoring and unit states. The camera boots from cold with **12 units active, 0 restarts, all four monitoring streams flowing** (chiller, slowboard, slowsignal, eventbuilder at 1–34 Hz).

**Decisions**
- **D-09a Run the upstream unit files unchanged; change behaviour only through drop-ins and extra units.** A symlink maps the hard-coded `%h/miniforge3/envs/sstcam` onto the venv. Everything that differs from a lab machine is in one visible place.
- **D-09b Never patch the camera source.** Workarounds are build flags, config patches, data preparation, or a launcher that sets mock options before the CLI starts. Each is documented where it is applied.
- **D-09c Backplane masked** (author: known broken; the first camera version has no backplane).
- **D-09d Slow-signal mock packet mode is a switch:** `example` for the clean baseline, `random` (the mock's default) kept as an injectable fault.
- **D-09e Hardware connect happens once at boot** (an extra one-shot unit), not on every restart, so "server restarted but never reconnected" stays observable, as on a real system.
- **D-09f The monitoring exporter uses the project's own reader API**, not a re-implemented protobuf parser.

**Findings about the real system** (evidence: build logs, journal and log excerpts in the capture)

| # | Finding | Consequence for the assistant |
|---|---|---|
| R1 | Per-process log timestamps are `yy-mm-dd HH:MM:SS`: **2-digit year, 1 s resolution, no timezone**. Central log (ICD format) has ms: `yy-mm-ddTHH:MM:SS.mmm`, also no timezone | Cross-process ordering below 1 s only from the central file; the parser must assume a zone (UTC in the box) |
| R2 | **Multi-line messages** (tracebacks, `Hardware error detected:` + one line per fault bit) produce continuation lines without timestamp or level, in both formats | Collector must reassemble records; naive line-based counting is wrong (v0 F1 again, in another form) |
| R3 | Files: `logs/log_<start>_<process>.txt` per process **start** (not per day) and `logs/sstcam-server_<date>.log` central; the private summary had the naming wrong | Each restart opens a new file: a restart is visible as a new file even without the journal |
| R4 | Branch HEAD deleted the combined slow-signal calibration CSV but the config and loader still require it: **slowsignal crash-loops (30+ restarts in minutes)** | Real "config/data mismatch after an update" incident, found without injecting anything |
| R5 | pointing `Requires=` slowsignal, so each slowsignal crash **stops pointing too** | Real dependency cascade: "why does pointing keep restarting?" has a non-local answer |
| R6 | Slow-signal mock fills packets with random words: every packet sets sensor fault bits, giving **~235 multi-line WARNINGs/s (~5–6 GB/day)**; the server does no rate limiting or de-duplication of repeated hardware warnings | Alert-fatigue scenario; a real failing RTD would do the same |
| R7 | Chiller and slowboard servers **publish no monitoring until `connect`**; the simulation adapter skips that step | Silence is a failure mode: absence of monitoring must be detected, not only bad values |
| R8 | Backplane server exits when `backplane_connection=DISCONNECTED`, and its stop hook then fails (`No server open`), so it loops | Known upstream (author); masked |
| R9 | Session start fails if `/data/SSTCAM/current` already exists (e.g. after power loss), and every server is `Requisite=` on the session | *Predicted from code, not yet reproduced:* a stale symlink would keep the whole camera down after an unclean restart |

**Build problems found upstream** (each has a documented workaround, not a source patch)
- The repo's systemd Dockerfile is truncated (P-08).
- `corel-mmio` (DESY GitLab) references an LFS object the remote no longer has, so any install with `git-lfs` present fails → `GIT_LFS_SKIP_SMUDGE=1`.
- `sstcam-eventbuilder/.../run_udp_stress_test.cc` stores `getopt()` in a `char` and compares with `-1`: **always true on arm64** (unsigned `char`), a hard error under `-Werror`, and an infinite loop without it → built with `-fsigned-char` (x86 semantics). Worth reporting upstream.
- The example server configs contain InfluxDB tokens in plain text; the patch script blanks them and redacts them in its output.

**Failures / dead ends (mine)**
- **X-09a** The AlmaLinux base image masks `systemd-logind`; without it the lingering user manager never starts, so none of the camera units ran. Found on first boot (`Failed to connect to bus`), fixed by unmasking.
- **X-09b** Guessed a class name in the camera code instead of looking it up; the launcher crash-looped slowsignal (`ImportError`) until fixed. Lesson: read the symbol before patching around it.
- **X-09c** Tooling slips: `docker cp` into a path hidden by a tmpfs mount; `sudo` `secure_path` overriding `PATH`; a heredoc to `docker exec` without `-i`. Each cost one iteration.
- **X-09d** The config patch script printed the old InfluxDB token into the (git-ignored) build log. Fixed: token keys are redacted, and the log line was removed.
- **X-09e** An offline test of example vs. random slow-signal packets reported 0 warnings for both, because it never reached the code that emits them. Replaced by a measurement in the running server: 0 warnings/60 s (example) vs. ~235/s (random).

**Evidence.** Image `camera-in-a-box:dev`, labels `sstcam.server.rev=…-gc8aef550`, `sstcam.server.branch=ssig-calib-conf-update`, `cambridge.rev=v0.3.0-rc1-37-g223ab40`. Baseline capture `lab/camera-in-a-box/captures/baseline-30m/` (git-ignored; summary in P-10).

---

## Failure register

Every failure in one table, with how it was found and where it was resolved. "Found by" matters: a failure found by a test or a measurement is worth more than one found by reading.

| ID | Introduced | Found | Found by | Failure | Impact | Resolution | Status |
|---|---|---|---|---|---|---|---|
| X-00a | P-00 | P-01 | Design review | Scope included actions, 6 agents, 5 external systems | Unbuildable, untestable | Scope cuts D-01a…D-01c | Resolved |
| X-01a | P-01 | P-01 | Self-assessment | No hands-on data on cost or effort | Estimates were guesses | Learning spike P-02/P-03 | Resolved |
| X-03a | P-03 | P-04 | Measurement | Substring keyword counts (3 vs. 1) | Confident wrong numbers | Levels as fields + deterministic events (M2); test T-DET-06 | Open → M2 |
| X-03b | P-03 | P-04 | Review | External stream; no ground truth | Not reproducible or scorable | Simulator (M1) | Resolved (tier A) |
| X-03c | P-03 | P-04 | Review | Tool schemas in 3 places, already drifting | Agent and MCP results not comparable | Single registry (M3) | Open → M3 |
| X-04a | P-03 | P-04 | Review | Eval: manual scoring, k=1, cost NaN | No trustworthy numbers | Eval harness (M4) | Open → M4 |
| X-07a | P-07 | P-07 | Test design | HV-trip ramp peaked between samples; telemetry never crossed the limit | Detection test would have been meaningless | Peak one sample earlier; test asserts crossing | Resolved |
| X-07b | P-07 | P-08 | Domain input | Simulator format and transport invented, not matched to the real system | Collector/detection would be tuned to a format that does not exist | Dialects + tiers B/C (D-08a, D-08b) | Open → M1b |
| X-09a | P-09 | P-09 | First boot | logind masked in base image; no user units ran | Camera never started | Unmask in image | Resolved |
| X-09b | P-09 | P-09 | Journal | Guessed class name; launcher crash-looped slowsignal | 1 iteration | Looked up symbol | Resolved |
| X-09d | P-09 | P-09 | Review of build log | Config token printed into build log | Secret in a local log | Redaction; log cleaned | Resolved |
| X-09e | P-09 | P-09 | Measurement | Offline test could not detect the warnings it was meant to count | False "no difference" | Measured in the running server | Resolved |

## Decision register

| ID | Decision | Step | Written up in |
|---|---|---|---|
| D-00a | Operator always decides | P-00 | [01](01-rationale.md) |
| D-00b | Core use case: explain a failure from team history | P-00 | [00](00-journey.md), [02 UC-01](02-requirements.md) |
| D-01a | Read-only by construction | P-01 | [ADR-0001](adr/0001-read-only-by-construction.md) |
| D-01b | Deterministic detection, LLM for language | P-01 | [ADR-0002](adr/0002-deterministic-detection-llm-for-language.md) |
| D-01c | Pipelines + one agent loop | P-01 | [ADR-0003](adr/0003-pipelines-first-one-agent-loop.md) |
| D-01e | Grounding validator | P-01 | [ADR-0005](adr/0005-grounding-validator.md) |
| D-01f | Model-agnostic, local-capable | P-01 | [ADR-0007](adr/0007-model-agnostic-provider-interface.md) |
| D-02b | SQLite collector + snapshots | P-02 | [ADR-0008](adr/0008-sqlite-timeline.md) |
| D-04a | Keep v0 as E1 baseline | P-04 | [04 E1](04-evaluation.md#3-experiments) |
| D-04c | In-repo simulator as ground truth | P-04 | [ADR-0004](adr/0004-synthetic-simulator-as-ground-truth.md) |
| D-05a | Single tool registry | P-05 | [ADR-0006](adr/0006-single-tool-registry-mcp.md) |
| D-05c | pass^k as headline reliability | P-05 | [04 §1](04-evaluation.md#layer-6--consistency) |
| D-05d | Judge calibration before use | P-05 | [04 §1](04-evaluation.md#layer-3--answer-quality-scored-by-question-type) |
| D-07a | Injector writes its own label | P-07 | [ADR-0004](adr/0004-synthetic-simulator-as-ground-truth.md) |
| D-07b | Expected events by kind/camera/time, not ID | P-07 | [04 §2](04-evaluation.md#2-dataset) |
| D-08a | Three data tiers, one label format (proposed) | P-08 | ADR pending |

---

## Tools and assistance

- **Brainstorm and roadmap (P-00, P-01):** written by the author. Frontier chat models were used to discuss and restructure drafts.
- **P-04 onwards:** Claude Code (Claude Opus) was used as a build-time tool, as the roadmap intends: reviewing the spike, reproducing defects, drafting docs and ADRs, writing code and tests. Scope, design decisions and acceptance were the author's. Commits made with assistance carry a `Co-Authored-By` trailer.
- **Run time:** no model is part of the deterministic core. The LLM layer is configurable ([ADR-0007](adr/0007-model-agnostic-provider-interface.md)).
