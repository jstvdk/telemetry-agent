# Runbook

What a shifter should know when the assistant reports something on an SST camera server: what the symptom means, what can cause it, how to tell the causes apart, what to do, and when to call someone. The LLM layer retrieves entries from here and must cite them by ID. It never invents a procedure.

## Rules

- **One file per symptom, not per fault.** An entry starts from what is visible (a detector event, a log message) and lists every cause we know, including causes that the lab cannot inject. Several faults look alike on purpose; telling them apart is the point of the *Checks* section.
- **Every statement has a source**: a finding about the real system (R-numbers in [PROVENANCE](../docs/PROVENANCE.md)), upstream code (`file:line` at `sstcam-server 2026-W28-93-gc8aef550`), a lab observation (P-numbers), or the operator. Nothing is sourced from the fault injector's code.
- **Status.** `ai-draft`: written with an AI tool from code and lab data, not yet checked by someone who runs the camera. `verified`: checked by an operator (name and date in the front matter). The assistant may cite an `ai-draft` entry only with a visible "draft" flag.
- **Actions are text.** The assistant is read-only (ADR-0001). A *Fix / mitigation* step is advice to a human. Steps marked **(to confirm)** are proposals nobody who operates the camera has approved yet.
- **Not in the runbook.** If no entry matches, the correct answer is to say so, give the evidence (event IDs), and escalate to the camera expert on duty. Making up a procedure is a failure, even if it happens to be right.

## Entry format

Front matter: `id`, `title`, `status`, `verified_by`, `verified_on`, `components`, `matches` (the detector events or log templates that should retrieve the entry; machine-readable), `sources`. Sections: Symptom, Meaning, Likely causes, Checks, Fix / mitigation, Escalation, History. Adapted from the author's roadmap (§7 "runbook factory"), with `matches` added because many symptoms here are not log messages.

## Entries

| ID | Symptom | Status |
|---|---|---|
| [RB-001](RB-001-subsystem-monitoring-silent.md) | One subsystem's monitoring stops | ai-draft |
| [RB-002](RB-002-all-monitoring-silent.md) | Monitoring from every subsystem stops at the same time, and it is lost | ai-draft |
| [RB-003](RB-003-gatherer-stall.md) | The gatherer writes nothing, then writes a late backlog | ai-draft |
| [RB-004](RB-004-slowsignal-module-silent.md) | One slow-signal module stops reporting | ai-draft |
| [RB-005](RB-005-server-restarts.md) | A server restarts, once or in a loop, with or without a traceback | ai-draft |
| [RB-006](RB-006-pointing-restarts-with-slowsignal.md) | Pointing restarts although nothing is wrong with pointing | ai-draft |
| [RB-007](RB-007-slowsignal-hardware-error-warnings.md) | Burst of slow-signal "Hardware error detected" warnings | ai-draft |
| [RB-008](RB-008-module-temperature-drift.md) | One module's temperature drifts relative to the others | ai-draft |
| [RB-009](RB-009-chiller-temperatures-change.md) | Chiller temperatures change | ai-draft |
| [RB-010](RB-010-known-benign-and-false-readings.md) | Known benign messages and known false readings | ai-draft |
| [RB-011](RB-011-session-does-not-start.md) | No camera server starts after a reboot | ai-draft |
| [RB-012](RB-012-data-disk-full.md) | The data disk is full | ai-draft |
