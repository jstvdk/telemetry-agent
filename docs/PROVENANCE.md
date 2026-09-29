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
| [P-10](#p-10--collectors-for-the-real-formats) | 2026-09-28 | Collectors | Parsers for logs, journal, monitoring; capture summary; tracebacks only in journal; central log misses boot | collect commit |
| [P-11](#p-11--clean-baseline-30-min-one-camera) | 2026-09-28 | Clean baseline | 30 min, 0 restarts; healthy camera writes no logs; mock channels flat; slow-signal mock constant | baseline commit |
| [P-12](#p-12--realistic-slow-signal-model-and-the-fault-harness) | 2026-09-28 | Slow-signal model + fault harness | 9 fault types into the real software, always reverted, labelled; I2C negative-temperature decode bug | harness commit |
| [P-13](#p-13--first-labelled-fault-run-b01-and-label-validation) | 2026-09-28 | First labelled run + label validation | 18/18 label evidence found; negative control 0/11 | validation commit |
| [P-14](#p-14--detector-v0-dev-set) | 2026-09-28 | Detector v0 on dev set | 18/18 after two design fixes; frozen as `detector-v0` | `detector-v0` |
| [P-15](#p-15--held-out-evaluation) | 2026-09-29 | Held-out evaluation | 15/16 recall, 0 false alarms (B02); 1.3 false alarms/h (B00b) | results commit |
| [P-16](#p-16--scorer-v1-one-event-one-expected-event) | 2026-09-29 | Scorer v1 | One event credits one expected event; B02 15/16 now computed, not hand-corrected | scorer commit |

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

## P-10 · Collectors for the real formats

**Goal.** Parse everything one camera writes into one entry model with citable references, and summarise a capture so that "normal" is measured, not assumed.

**Method.** A second camera (`cam-02`) was used for experiments so the baseline on `cam-01` stayed untouched. Three faults were injected by hand: slow-signal packets set to `random` (sensor-fault flood), `SIGKILL` on the chiller, and the calibration file hidden for about 10 s. The parsers were written against that output; the test fixtures are small cuts of it.

**Done.** `src/shiftassist/collect/`: `Entry` (with `ref = source:line` as the citation handle) and `Sample`; parsers for the pipe and central formats (multi-line records reassembled; the separator may occur inside messages); a journal parser (systemd lifecycle events classified; stdout continuation lines attached to their record; tracebacks reassembled per PID); a monitoring flattener; and `shiftassist-collect summarise <capture>` → `SUMMARY.md`. 14 tests on real fixtures. The full cam-02 capture (235k log lines, 198k journal records) parses in ~3 s.

**Findings about the real system (continued)**

| # | Finding | Consequence for the assistant |
|---|---|---|
| R10 | **Crash tracebacks reach only the journal.** Uncaught exceptions go to stderr: not to the per-process file, not to the central log. In the journal they arrive one line per record, at priority INFO | A collector that reads only log files sees a process vanish and restart *without a reason*. Tracebacks must be reassembled and re-levelled |
| R11 | **The central log misses the startup of every server that starts before the gatherer listens** (7 of 7 servers at boot, 16–93 records each: the config banner, IDs, versions). Units use `After=sstcam-gatherer`, but the gatherer is `Type=simple`, so "started" means "process exists", not "socket ready" | "Which config did it load?" cannot be answered from the central log. Read per-process files; upstream fix: `Type=notify` or a readiness check |
| R12 | **The gatherer's own per-process file is a full second copy of the central log** (every record forwarded to it is also written to its local file) | 2× storage; the collector must skip that file or de-duplicate |
| R7 ✔ | Reproduced as an incident: after the chiller was killed and restarted, it sent **no monitoring for the rest of the run** (22 messages vs 114 from slowboard), with no log line saying so | Detect missing monitoring per subsystem; a restart without a following `connect` is suspect |
| R13 | In `random` packet mode the slow-signal module slot field is random too: 253 distinct "modules" for 32 real ones | The flood fault also corrupts identity fields; label it as such |

**Failures / dead ends (mine)**
- **X-10a** The first journal parser produced 153k one-line "stdout" entries. journald stores each continuation line of a multi-line record as a separate record, and those were not attached. Found by counting entry kinds; fixed by grouping per PID.
- **X-10b** A test fixture was cut too narrowly and missed the restart record it was meant to test. The test failed for the right reason; fixed the fixture, not the test.
- **X-10c** mypy caught a variable name reused for strings in one loop and datetimes in another, in the report renderer.

---

## P-11 · Clean baseline (30 min, one camera)

**Goal.** Measure what "normal" looks like before injecting anything, so detection is tuned against data, not guesses.

**Done.** `cam-01` ran untouched for 30.6 min from a cold boot; captured with `capture.sh baseline-30m` and summarised with `shiftassist-collect summarise` (report: `captures/baseline-30m/SUMMARY.md`, git-ignored).

**Result**

| | |
|---|---|
| Units | 11 active, **0 restarts**; journal: one start per unit, no exits, **0 tracebacks** |
| Logs | 620 entries, **all within the first 12 s** (18:21:53–18:22:05). The last 30.3 min wrote **no log lines at all** |
| WARNING+ | 1: the known, benign controller "simulation override" notice |
| Central log | still misses the boot records of 6 servers (R11 reproduced) |
| Monitoring | chiller, slowboard, eventbuilder at 1.0 Hz each for the whole run; slowsignal 31.9 Hz |
| Volume | ~80 MB data + 112 MB decoded monitoring per camera per 30 min (monitoring dominates) |

**Findings**

| # | Finding | Consequence for the assistant |
|---|---|---|
| R14 | **A healthy camera writes no logs after start-up.** Logs are purely an event stream | "Nothing in the logs" means nothing, not "healthy". Liveness must come from monitoring cadence (1 Hz per subsystem) and the journal. Rates must be computed over the capture window, not the log window |
| R15 | **Several mock channels are flat or physically impossible:** slowboard humidity −25.8 %, external temperature −40 °C, all power-rail currents 0, fan speeds 0 (39 flat channels in total) | Rules on these channels would be meaningless or fire constantly. Detection needs a per-channel "has signal" flag learned from the baseline |
| R16 | **The slow-signal mock's clean (`example`) mode sends one constant packet:** every temperature fixed (std 0), HV 12 V, and every packet claims module slot 1 | No realistic slow-signal data and no way to inject a per-module fault through the mock as shipped. Needed: a realistic packet generator (real packet class and server path, plausible per-module values) |

**Failures / dead ends (mine)**
- **X-11a** `capture.sh` treated tar's "file changed as we read it" (expected on a live camera) as a failure, so the rename step did not run. Fixed: exit status 1 tolerated, >1 fails.
- **X-11b** The first summary computed rates over the log window (12 s) instead of the capture window (30.6 min), overstating rates ~150×. R14 made this visible. Fixed: the window spans all sources, and the quiet period is reported.
- **X-11c** The first background capture job would have been killed by the tool's 10-min timeout. Replaced by a detached process before it fired.

---

## P-12 · Realistic slow-signal model and the fault harness

**Goal.** Make every fault class injectable into the *real* camera software with exact ground truth, including per-module slow-signal faults, which the shipped mock could not produce (R16).

**Done**
- `lab/camera-in-a-box/lab/slowsignal_model.py`: per-TARGET-module values (nominal + fixed module offset + shared ambient wave + noise), encoded with exact inverses of the server's own conversions and sent through the real server path. A control file changes behaviour at runtime without restarts: `drift`, `offset`, `sensor_fault` (fault bits on chosen RTDs), `dead` (module stops sending). Verified live: 32 modules with slots 0–31, module means spread ±1.2 °C, noise ~0.03 °C, 0 warnings. A 60 °C/h drift gave +0.67 °C in 40 s; a dead module sent 0 packets while dead; one broken RTD gave exactly 1 warning/s.
- `src/shiftassist/lab/`: `Box` (docker exec; every command logged with the container-clock time), a fault catalog of 9 types (`process_crash`, `process_hang`, `gatherer_down`, `calibration_missing`, `disk_full`, `slowsignal_drift`, `sensor_fault`, `module_dead`, `chiller_ramp`), and a runner. The runner refuses an unhealthy camera, reverts in `finally`, falls back to an idempotent `reset_to_nominal` if a revert fails, verifies recovery before the next fault, and aborts the rest of the run if the camera does not recover. `disk_full` refuses to run unless `/data` is a small tmpfs. CLI: `shiftassist-lab run|check|reset`, with `--dry-run`. 12 tests against a fake container.
- Label contract extended (shared with tier A): event kind `log_burst`; `entity` on expected events (e.g. `tm07`).
- Scenarios: `B00` (30-min clean baseline with the realistic model) and `B01` (8 faults, one of each type except `disk_full`).

**Decisions**
- **D-12a Faults change the camera's situation, never its logs.** The harness kills, freezes, hides files, or changes sensor readings; every log line and journal entry in a capture is written by the camera software itself.
- **D-12b The chiller/slowboard crash label includes a monitoring gap** until reconnect (R7): the hold is the time until the "operator" reconnects.
- **D-12c Label times come from the container clock**, which is the clock the camera stamps its data with.
- **D-12d Nominal slow-signal values are assumptions** (plausible lab-room numbers), stated in the model's docstring. The model provides realistic *structure* (per-module identity, noise, drift), not measured physics.

**Findings about the real system (continued)**

| # | Finding | Consequence |
|---|---|---|
| R17 | **The I2C aux/primary board-temperature decoder is wrong for every negative temperature.** It shifts the whole word, so the sign bit lands in the magnitude: −5 °C decodes as −133 °C (sign-magnitude input) or −251 °C (two's complement). Positive values are exact. Found by round-tripping the encoders through the server's decoders | A cold camera (outdoors at night, cold start) reports absurd board temperatures and can trip limit rules. Worth reporting upstream |
| R18 | **The slow-signal hardware-error WARNING names neither module nor sensor** ("Hardware error detected: Sensor Hard Fault …"), and the published temperature stays plausible because the fault bits are masked off | A broken RTD cannot be located from the logs or from monitoring. The assistant can only say "some sensor on some module", unless the packet source is logged |
| R19 | The chiller mock treats a temperature override of 0 as "no override" (`override or setpoint`) | 0 °C cannot be simulated; `temperature 0` is the way to clear the override |

**Failures / dead ends (mine)**
- **X-12a** The monitoring exporter dropped every protobuf field at its default value, including `tm_slot = 0` and any reading of exactly 0.0. Found when the per-module check raised `KeyError: 'tm_slot'`. Fixed with `always_print_fields_with_no_presence=True`. The earlier baseline decode (P-11) was affected only for zero-valued fields.
- **X-12b** An expected timestamp in a harness test was computed by hand, wrongly; the code was right. The test now states the reference time.

---

## P-13 · First labelled fault run (B01) and label validation

**Goal.** Produce the first labelled data from the real camera software, and prove the labels are right *before* any detector is scored against them.

**Done.** Two fresh cameras from the same image, run in parallel:
- `cam-01` → **B00**: 31 min clean baseline with the realistic slow-signal model. 0 restarts, 0 tracebacks, only the known controller notice; all 32 modules at 0.99 Hz.
- `cam-02` → **B01**: 8 faults over 36 min, all injected, reverted and recovered on schedule; no abort, no failed command.

Then `shiftassist-collect verify-labels` checked every expected event against the camera's own data, and a **negative control** applied the same checks, at the same offsets, to the clean B00 capture.

**Result**

| Check | Result |
|---|---|
| B01 labels on B01 (does the evidence exist?) | **18/18** |
| B01 labels on clean B00 (do the checks fire on a healthy camera?) | **0/11** (7 inconclusive: B00 is shorter than B01, so those windows fall outside it) |

What the faults actually did (measured, not assumed):

| Fault | Evidence in the capture |
|---|---|
| chiller SIGKILL, 2 min before reconnect | chiller monitoring silent **127 s**: restart ≈ 7 s after reconnect |
| RTD fault, module 12 | 90 WARNINGs at 0.93/s, none before |
| slowboard frozen 90 s | monitoring silent 91 s; **nothing in the journal** (a freeze is not an exit) |
| module 5 dead 2 min | module silent 122 s |
| calibration missing, ~70 s | 6 `FileNotFoundError` tracebacks, 19 stop/exit events (crash loop), pointing stopped 8 times, and its stop hook failing too |
| drift 6 °C/h, module 7 | +6.6 °C/h in the window vs +0.6 °C/h before (z ≈ 50) |
| chiller ramp 23→30 °C | +67 °C/h over the window (ramp + hold), z ≈ 70 |
| gatherer stopped 90 s | all four monitoring sources silent **108 s** at the same moment: ~18 s gatherer start-up on top of the hold |

**Decisions**
- **D-13a A label is not trusted until its evidence is found in the data, and a negative control shows the check does not fire on a healthy camera.** This validates the ground truth, which is separate from, and comes before, detector evaluation.
- **D-13b Three outcomes, not two:** a check whose window is not covered by the capture is *inconclusive*, never "found" or "missing".

**Failures / dead ends (mine)**
- **X-13a The first negative control reported 4 false "gaps".** The shifted windows ran past the end of the shorter baseline, and "no data after the capture ended" was read as silence. Fixed with the inconclusive outcome (D-13b). Without the negative control this bug would have inflated every later gap result.
- **X-13b** A test expected a 90 s silence; the correct value is 91 s (last message at 199 s, next at 290 s). The code was right.

---

## P-14 · Detector v0 (dev set)

**Goal.** A deterministic detector (ADR-0002): thresholds learned from a clean capture, rules that never read labels, events with IDs and code-written evidence.

**Method.** Held-out data was separated *before* any detector code: scenarios B02 (10 faults, new modules, units, magnitudes, order, plus a hard slow drift) and B00b (45-min clean run) were committed first (`ea6ac47`), and the runs started. B01 was the dev set; it had already been inspected during label validation.

**Done.** `src/shiftassist/detect/`: profile (per-source cadence, per-channel slope thresholds = max baseline |slope| x 1.5 with a floor, WARNING rates, known templates); rules R-GAP-01, R-RST-01, R-TB-01, R-BURST-01, R-SIG-01, R-TRD-01/02; scorer (recall any/exact module, strict/lenient precision, false alarms per hour, delay). 5 rule tests on synthetic captures. Frozen and tagged `detector-v0` before the held-out captures were written.

**Dev results (B01).** First run: recall 78 %, 214 events, strict precision 7 %. After the two fixes below: recall 18/18, exact 17/18, 23 events, 0 false alarms; B00 on itself 0 events.

**Decisions**
- **D-14a Held-out data is committed before the code it will evaluate, and the code is tagged before the held-out data exists.** The git history is the evidence.
- **D-14b Slow-signal trends are computed on each module's deviation from the camera-wide median**, after centring every module on its own median, so shared ambient changes and module drop-outs do not look like drifts.
- **D-14c Events are stamped at detection time**, the time an online system could have known, not at the start of the analysis window.
- **D-14d Labels are not edited after seeing detector output.** The chiller ramp moves all four chiller temperatures, but B01/B02 labels list two; the catalog is fixed for future runs, and past labels stay as recorded.

**Failures / dead ends (mine)**
- **X-14a Trend events stamped at the window start** (up to 3 min before the drift began) could not match any label: trend recall 0/4 with the right signal present. Found by comparing event times with label windows.
- **X-14b 193 false trend events across all modules.** When one module stopped sending, the raw cross-module median shifted by a fraction of the module-offset spread, a step that looked like a slope on every other module. Fixed by centring (D-14b); a regression test was verified by mutation (it fails when the centring is removed).
- **X-14c Incomplete label:** the chiller ramp label listed 2 of the 4 temperatures the fault moves (D-14d).

---

## P-15 · Held-out evaluation

**Result** (full table and caveats: [results.md](results.md))

| data | recall (conservative) | exact module | events | false alarms |
|---|---:|---:|---:|---:|
| B02 (held-out, 10 faults) | **15/16** validated expected events | 14/16 | 21 | **0** |
| B00b (held-out, clean, 46 min) | – | – | 1 | **1.3 per hour** |

The hard drift (1.5 °C/h, ~0.15 °C in 6 min) was detected after 131 s.

**Findings**

| # | Finding | Consequence |
|---|---|---|
| R20 | **A frozen gatherer loses no monitoring.** Publishers keep sending, the messages queue, and the gatherer writes them when it resumes, with the original source timestamps (61/61 messages per 1 Hz source in a 62 s freeze; slow-signal at its full 31.7/s, with at most a 16 s silence on some module) | A gatherer hang is not visible as a monitoring gap after the fact. It is visible as late arrival (write time vs. message timestamp) and in the gatherer's own logs. The catalog's expectation for `process_hang gatherer` was wrong |

**Decisions**
- **D-15a Score against validated expectations only.** `shiftassist-detect score --only-validated` drops expected events whose evidence is absent in the data (label validation, D-13a), and reports how many. Unvalidated numbers are published alongside.
- **D-15b Conservative reading over scorer output:** one B02 match that the scorer credited belongs to an adjacent fault, so it is counted as a miss.

**Failures / dead ends**
- **X-15a (mine) Wrong label:** `process_hang gatherer` was labelled with gaps on all four sources; 3 of 4 had no gap (R20). Caught by label validation before scoring.
- **X-15b (mine) Scorer double attribution:** with overlapping fault windows, one event could satisfy two labels. Found by reading the per-event table; to be fixed so that one event is credited to one label.
- **X-15c False alarm on held-out clean data:** chiller trend +3.87 °C/h vs threshold 3.86 °C/h. The threshold (max of a 31-min baseline x 1.5) is too tight for longer runs. Not tuned after seeing it; left for the next detector version.

**Next**
1. Scorer: one event, one label.
2. Thresholds from a longer baseline / tail quantiles; re-measure false alarms per hour on a new held-out clean run.
3. `process_hang gatherer`: detect late arrival instead of gaps.
4. LLM layer on top of the event timeline: explain and correlate, with citations validated against event IDs.

---

## P-16 · Scorer v1: one event, one expected event

**Goal.** Fix X-15b. The scorer credited every matching event to every expected event it fitted, so one event could explain two overlapping faults, and the published B02 number had to be corrected by hand.

**Plan for the next steps (agreed 2026-09-29).** Scorer fix (this entry) → longer clean baseline → detector v1 (late arrival for a frozen gatherer, thresholds from more data) → runbook (drafted, then corrected by the author, then frozen) → new held-out set B03, recorded after both the detector and the runbook are frozen → LLM layer and its evaluation. The runbook question raised at this point, "is a runbook built from injected faults overfitting?", is answered in P-19.

**Done.** `src/shiftassist/detect/score.py`: credit is a minimum-cost bipartite matching between expected events and detector events (Hungarian method). Cost, in order: an unmatched expected event, then a partial (module-less) match, then the delay from fault start to event. Events that match an already-credited expected event are reported as *duplicates*: they count for lenient precision, not strict. 5 scorer tests, including a brute-force optimality check on 300 random cases.

**Result.** detector-v0 events unchanged; only the credit rule changed.

| data | scorer v0 | scorer v1 |
|---|---|---|
| B01 | 18/18, exact 17/18, strict precision 78 % | same |
| B02 (validated) | printed 16/16; published 15/16 after a hand correction | **15/16**, exact 14/16, strict precision 71 % (was 76 %) |
| B00b | 1 false alarm | same |

The B02 strict precision drops because a second trend event on the same drifting module is now a duplicate. The miss is now the gatherer-freeze gap (L08), and the gap is credited to the calibration fault (L09), as in the hand reading.

**Decisions**
- **D-16a Credit assignment is one-to-one and prefers the most plausible fault**, not the first label in the file. This matters beyond the metric: the LLM layer will explain events by the fault they belong to.
- **D-16b Re-scoring held-out data with a new scorer is allowed; re-running a new detector on it is not.** The scorer does not see the data before scoring and changes no detector output. The old reports are kept next to the new ones (`SCORE_scorer-v0.md`).

**Failures / dead ends (mine)**
- **X-16a The first fix was a maximum matching (Kuhn) with tie-breaks by processing order.** It produced the right count (15/16) but credited the gap to the wrong fault (L08, 75 s after its start, instead of L09, 8 s after). Found by diffing the per-label table against the hand reading. Replaced by the minimum-cost matching; a test fixes the B02 case.
- **X-16b A scorer test was set up wrongly:** its "second" event also fell inside the first label's window (end + tolerance), so either assignment was valid. The code was right. A mutation run (greedy assignment swapped in) confirmed the rebuilt test fails when matching is not maximal.

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
| X-10a | P-10 | P-10 | Counting entry kinds | Journal continuation lines became 153k separate entries | Multi-line records split | Group per PID | Resolved |
| X-10b | P-10 | P-10 | Failing test | Fixture cut missed the record under test | Test could not pass | Re-cut fixture | Resolved |
| X-11a | P-11 | P-11 | Capture output | Live-file tar warning aborted the rename | Capture in wrong layout | Tolerate exit 1 | Resolved |
| X-11b | P-10 | P-11 | Baseline review | Rates over log window, not capture window | Rates ~150x too high | Window across all sources | Resolved |
| X-12a | P-10 | P-12 | KeyError in per-module check | Exporter dropped default-valued protobuf fields (slot 0, zeros) | Module 0 and zero readings invisible | Always print fields | Resolved |
| X-13a | P-13 | P-13 | Negative control | Windows past the capture end counted as silence | 4 false gaps | Inconclusive outcome | Resolved |
| X-14a | P-14 | P-14 | Event vs label times | Trend events stamped at window start | Trend recall 0/4 | Detection-time stamps | Resolved |
| X-14b | P-14 | P-14 | Event counts | Median shift when a module dropped out | 193 false trends | Centred common mode + regression test | Resolved |
| X-15a | P-12 | P-15 | Label validation | Gatherer hang labelled as gaps; data is buffered, not lost | 3 invalid expected events | Excluded; catalog to fix | Open |
| X-15b | P-14 | P-15 | Reading per-event table | Scorer can credit one event to two overlapping labels | Recall overstated by 1 | Min-cost one-to-one matching (P-16) | Resolved |
| X-16a | P-16 | P-16 | Diff vs hand reading | Max matching broke ties by file order; gap credited to wrong fault | Right count, wrong attribution | Min-cost matching + test | Resolved |
| X-15c | P-14 | P-15 | Held-out clean run | Threshold from short baseline too tight | 1.3 false alarms/h | Longer baseline / tail threshold | Open |

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
| D-08a | Three data tiers, one label format | P-08 | ADR pending |
| D-12a | Faults change the situation, never the logs | P-12 | [lab README](../lab/camera-in-a-box/README.md) |
| D-13a | Labels validated against data + negative control before scoring | P-13 | this file |
| D-14a | Held-out committed before code; code tagged before held-out data | P-14 | [results](results.md) |
| D-14d | Labels are not edited after seeing detector output | P-14 | this file |
| D-15a | Score against validated expectations; publish unvalidated too | P-15 | [results](results.md) |
| D-16a | One event credits one expected event, most plausible fault first | P-16 | this file |
| D-16b | New scorer may re-score held-out; new detector may not | P-16 | this file |

---

## Tools and assistance

- **Brainstorm and roadmap (P-00, P-01):** written by the author. Frontier chat models were used to discuss and restructure drafts.
- **P-04 onwards:** Claude Code (Claude Opus) was used as a build-time tool, as the roadmap intends: reviewing the spike, reproducing defects, drafting docs and ADRs, writing code and tests. Scope, design decisions and acceptance were the author's. Commits made with assistance carry a `Co-Authored-By` trailer.
- **Run time:** no model is part of the deterministic core. The LLM layer is configurable ([ADR-0007](adr/0007-model-agnostic-provider-interface.md)).
