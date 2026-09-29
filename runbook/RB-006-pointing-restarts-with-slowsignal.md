---
id: RB-006
title: Pointing restarts although nothing is wrong with pointing
status: ai-draft
verified_by:
verified_on:
components: [pointing, slowsignal]
matches:
  - {kind: restart, subsystem: pointing}
sources:
  - sstcam-orchestrator/units/sstcam-pointing.service:5 (Requires=sstcam-slowsignal.service)
  - R5 (each slow-signal crash stops pointing too)
  - P-13 (lab: slow-signal crash loop → pointing stopped 8 times, and its stop hook failed too)
---
## Symptom
`sstcam-pointing.service` is stopped and started, possibly many times, without a traceback of its own.

## Meaning
The pointing unit `Requires=` the slow-signal unit. Whenever slow-signal stops or crashes, systemd stops pointing too, then starts it again with slow-signal. The cause is almost never in pointing.

## Likely causes
1. **Slow-signal restarted** (crash, crash loop, or a manual restart). Look at RB-005 for why.
2. **Pointing itself crashed.** Then there is a pointing traceback and slow-signal is stable.

## Checks
- Did `sstcam-slowsignal.service` stop or exit within a second before each pointing stop?
- Is there a pointing traceback in the journal?

## Fix / mitigation
- Cause 1: handle the slow-signal problem (RB-005); pointing follows by itself.
- Cause 2: treat as RB-005 for pointing.

## Escalation
As for the underlying slow-signal problem.

## History
- Real system (R5), reproduced in the lab (P-13).
