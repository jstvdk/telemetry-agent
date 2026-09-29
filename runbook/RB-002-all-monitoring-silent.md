---
id: RB-002
title: Monitoring from every subsystem stops at the same time, and it is lost
status: ai-draft
verified_by:
verified_on:
components: [gatherer, host]
matches:
  - {kind: gap, subsystem: [chiller, slowboard, eventbuilder, slowsignal], entity: null, simultaneous: all}
  - {kind: restart, subsystem: gatherer}
sources:
  - 'sstcam-orchestrator/units/sstcam-gatherer.service:4 (every server is Requisite= on the session; the gatherer records monitoring and the central log)'
  - 'R11 (servers starting before the gatherer listens lose their start-up records in the central log)'
  - 'P-13 (lab: gatherer stopped 90 s → all four sources silent 108 s, about 18 s of gatherer start-up on top)'
---
## Symptom
Every monitoring source goes silent within a few seconds of each other, and the data for that period never appears later. (If it appears later, late, see RB-003.)

## Meaning
One component that all monitoring passes through is down: the gatherer, or the host itself. The individual servers are usually fine.

## Likely causes
1. **The gatherer was stopped or crashed.** Journal: a stop or exit, then a start, of `sstcam-gatherer.service`. The central log also has a hole.
2. **The host was overloaded, suspended or lost its clock** (not reproduced in the lab).
3. **All servers stopped** (the session or `sstcam.target` stopped). Journal: stops of every unit.

## Checks
- Journal for `sstcam-gatherer.service` and for the session unit around the start.
- Are the servers themselves alive? `sstcam <subsystem> ping-server` for one or two of them. **(untested in the lab)**
- Did the per-process log files keep being written? The gatherer does not write those; a server that logs during the silence was alive.

## Fix / mitigation
- Cause 1: if systemd has not restarted the gatherer, start it. After it is back, expect about 20 s before data flows. Monitoring for the gap is lost; note it in the shift log. **(to confirm)**
- Cause 3: find out who stopped the camera before restarting anything.

## Escalation
If the gatherer does not stay up after one restart, call the camera software expert. **(to confirm: who)**

## History
- Lab (P-13): `systemctl stop` of the gatherer for 90 s → 108 s of silence on all sources; the restart took about 18 s.
