---
id: RB-011
title: No camera server starts after a reboot
status: ai-draft
verified_by:
verified_on:
components: [session, orchestrator]
matches:
  - {kind: restart, subsystem: session}
  - {kind: gap, subsystem: [chiller, slowboard, eventbuilder, slowsignal], entity: null, simultaneous: all, from_start: true}
sources:
  - 'R9 (session start fails if /data/SSTCAM/current already exists; every server is Requisite= on the session). Predicted from code, not reproduced.'
  - 'sstcam-orchestrator/units/sstcam-gatherer.service:4 (Requisite=sstcam-session.service; the same in every server unit)'
---
## Symptom
After a reboot or power loss, none of the camera servers is running, and there is no monitoring at all.

## Meaning
All servers depend on the session unit. If the session fails, nothing else starts.

## Likely causes
1. **A stale `/data/SSTCAM/current` link** left by an unclean shutdown makes the session start fail (R9, predicted from code).
2. **The data disk is not mounted or full.**

## Checks
- Journal for the session unit: the failure message.
- Does `/data/SSTCAM/current` exist, and where does it point?

## Fix / mitigation
- Cause 1: the camera software expert decides whether the link can be removed. **(to confirm)**

## Escalation
Camera software expert. **(to confirm)**

## History
- Not observed yet; derived from the unit files and the session code (R9).
