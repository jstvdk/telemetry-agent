---
id: RB-001
title: One subsystem's monitoring stops
status: ai-draft
verified_by:
verified_on:
components: [chiller, slowboard, eventbuilder, slowsignal, gatherer]
matches:
  - {kind: gap, subsystem: [chiller, slowboard, eventbuilder, slowsignal], entity: null}
sources:
  - 'R7, R7 ✔ (chiller/slowboard publish nothing until `connect`; not reconnected after a restart)'
  - 'R14 (a healthy camera writes no logs; liveness comes from monitoring cadence)'
  - 'sstcam-orchestrator/units/sstcam-chiller.service:13 (Restart=on-failure)'
  - 'sstcam-cli/sstcam_cli/cli/chiller/{connect,ping_server,ping_hardware}.py (same for slowboard)'
  - 'P-13 (lab: chiller killed → 127 s silent until reconnect; slowboard frozen 90 s → 91 s silent, nothing in the journal)'
---
## Symptom
No monitoring from one subsystem (chiller, slowboard, event builder, or the whole slow-signal server) for longer than its normal interval (1 s) allows. The other subsystems keep reporting.

## Meaning
The camera does not complain about missing monitoring by itself: there is usually no log line (R14). The monitoring stream is the only sign.

## Likely causes
1. **The server crashed and was restarted by systemd but is not connected to its hardware.** Chiller and slowboard servers publish nothing until someone runs `connect` (R7). The journal shows an exit and a start for the unit shortly before the silence.
2. **The server is alive but frozen** (deadlock, blocked I/O, stopped process). systemd sees nothing wrong, so the journal is quiet; the unit is `active`.
3. **The hardware connection was lost** (device powered off, network or serial link down) while the server kept running. Not reproducible in the lab (mocked hardware).
4. **The server was stopped deliberately** (an operator or a maintenance script). The journal shows a stop without an exit code.

## Checks
- Journal for the unit around the start of the silence: exit + start → cause 1; stop without a failure → cause 4; nothing → cause 2 or 3.
- `sstcam <subsystem> ping-server`: no answer → cause 2 (frozen). **(untested in the lab)**
- `sstcam <subsystem> ping-hardware` (chiller, slowboard): server answers but hardware does not → cause 3. **(untested in the lab)**
- Other subsystems still reporting? If *all* stopped together, see RB-002 or RB-003 instead.

## Fix / mitigation
- Cause 1: reconnect the server to its hardware (`sstcam chiller connect`, `sstcam slowboard connect`). **(to confirm: is this the shifter's action, and is anything else needed after a reconnect?)**
- Cause 2: restart the unit. **(to confirm: who may restart a camera server during observation?)**
- Cause 3: hardware issue; do not restart software repeatedly. Escalate.
- Cause 4: check the shift log / e-log for a planned intervention before acting.

## Escalation
Chiller silent for more than a few minutes during operation: the camera's cooling is not being monitored. **(to confirm: time limit, and who is on call for cooling)**

## History
- Lab (P-13): chiller SIGKILL → restarted in about 7 s, then silent until reconnect (127 s). Slowboard frozen 90 s → silent 91 s with no journal entry.
