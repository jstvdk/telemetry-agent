---
id: RB-003
title: The gatherer writes nothing, then writes a late backlog
status: ai-draft
verified_by:
verified_on:
components: [gatherer]
matches:
  - {kind: gap, subsystem: gatherer, rule: R-STALL-01}
sources:
  - 'R20 (a frozen gatherer loses no monitoring; it writes the queued messages late with their original timestamps)'
  - 'sstcam-gatherer/sstcam_gatherer/handler.py:76 (the gatherer stamps each message with its own receive time)'
  - 'P-17 (lab: 61 s freeze → 2021 messages from 4 sources up to 61 s late, none lost)'
---
## Symptom
The gatherer's output stops for all sources at once; when it resumes, the messages it writes carry timestamps from the silent period. Nothing is lost.

## Meaning
The gatherer process was not reading for a while, but the servers kept sending and the messages queued. Every server is fine. Live displays fed by the gatherer were frozen during that time, and alarms based on them were late.

## Likely causes
1. **The gatherer process was blocked** (slow disk, a long garbage collection, stopped by a signal, the host swapping).
2. **The host was paused** (VM suspend, heavy load). All processes would then look late, not only the gatherer.

## Checks
- Journal: nothing for the gatherer unit is expected (it did not exit). An exit and start would point to RB-002 instead.
- Host load and disk latency around the time. **(to confirm: what host metrics are available on the camera server)**
- Did it happen more than once? Repeated stalls point to a resource problem, not a one-off.

## Fix / mitigation
- A single stall with no data lost needs no action beyond a shift-log note.
- Repeated stalls: report to the camera software expert with the times. **(to confirm)**

## Escalation
Stalls longer than a few minutes delay every monitoring-based alarm. **(to confirm: limit)**

## History
- Lab (P-17): gatherer SIGSTOP for 61 s. The source-time gap rule saw nothing (R20); the stall rule found it from write silence plus late arrival.
