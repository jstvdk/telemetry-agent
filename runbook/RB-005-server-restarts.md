---
id: RB-005
title: A server restarts, once or in a loop, with or without a traceback
status: ai-draft
verified_by:
verified_on:
components: [chiller, slowboard, slowsignal, eventbuilder, gatherer, pointing, target, controller]
matches:
  - {kind: restart}
  - {kind: traceback}
  - {kind: new_signature, template: "traceback|*"}
sources:
  - 'R10 (crash tracebacks reach only the journal, one line per record at INFO)'
  - 'R3 (each process start opens a new per-process log file)'
  - 'R4 (real incident: calibration CSV removed on the branch while config and loader still need it → slow-signal crash loop, 30+ restarts in minutes)'
  - 'sstcam-orchestrator/units/*.service (Restart=on-failure on every server)'
  - 'P-13 (lab: calibration file hidden ~70 s → 6 FileNotFoundError tracebacks, 19 stop/exit events)'
---
## Symptom
systemd restarts a camera server. Either once (exit, start, then stable) or repeatedly (a crash loop: exit, start, exit …). Tracebacks, if any, are in the journal only (R10).

## Meaning
`Restart=on-failure` hides a crash from anyone who only looks at "is it running?". The exception in the traceback is the most useful single fact.

## Likely causes
1. **A file the server needs at start-up is missing or unreadable** (calibration table, configuration). Traceback: `FileNotFoundError` / `PermissionError` with the path. Crash loop, because every start fails the same way (R4).
2. **The data disk is full** (`OSError: [Errno 28] No space left on device`). In the lab this did *not* restart anything: see RB-012.
3. **A one-off crash** (bug, killed by the OOM killer or by someone). One restart, then stable. The journal exit status tells a signal (`status=9/KILL`) from an exception (`status=1/FAILURE`).
4. **A dependency restarted** (see RB-006 for pointing).
5. **The server was restarted on purpose** (stop + start, no failure).

## Checks
- The exception type and the path in the traceback (causes 1, 2).
- Exit code and signal in the journal (cause 3 vs. 1).
- Disk usage of `/data` (cause 2).
- Was the software or configuration changed shortly before (new release, config reload)? A loop that starts right after a change points to the change.
- Crash loop still going? Count starts in the last minutes.

## Fix / mitigation
- Cause 1: restore the missing file (from the release or the previous configuration) and let systemd restart the server. Do not edit calibration or configuration by hand. **(to confirm: where the reference copies live and who restores them)**
- Cause 2: free space according to the data policy. Never delete raw data without permission. **(to confirm)**
- Cause 3: note it in the shift log with the exit status; if it repeats, escalate.
- A crash loop that does not stop within a few minutes: stop restarting and escalate. **(to confirm)**

## Escalation
Camera software expert, with the traceback and the time of the first crash. **(to confirm: who)**

## History
- Real system (R4): calibration table removed from the branch but still required → slow-signal crash loop at start-up.
- Lab (P-13): calibration file hidden for about 70 s → crash loop with `FileNotFoundError`, which also stopped pointing 8 times (RB-006).
