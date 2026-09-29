---
id: RB-008
title: One module's temperature drifts relative to the others
status: ai-draft
verified_by:
verified_on:
components: [slowsignal, TARGET module, cooling]
matches:
  - {kind: trend, subsystem: slowsignal, entity: "tm*"}
sources:
  - 'P-14 (trend rule on each module''s deviation from the camera-wide median; shared changes cancel)'
  - 'P-12, D-12d (lab slow-signal values: realistic structure, assumed nominal numbers)'
  - 'P-15 (lab: 1.5 °C/h drift on one sensor detected after 131 s)'
---
## Symptom
A temperature on one module changes faster than normal *relative to the other modules*. Changes shared by all modules (ambient, chiller) are removed before this test, so this is local.

## Meaning
Something is heating or cooling that module alone, or one of its sensors is going wrong.

## Likely causes
1. **The module dissipates more power** (electronics fault, a changed operating point). All sensors on that module move together.
2. **Local cooling problem** near that module. Neighbouring modules may follow more slowly. **(to confirm: is this physically plausible in the SST camera cooling layout?)**
3. **One sensor degrading.** Only that sensor moves; the other sensors on the module stay flat.

## Checks
- One sensor or all sensors of the module? (cause 3 vs. 1/2)
- Neighbouring modules drifting in the same direction, smaller? (cause 2)
- Any configuration change or HV change on that module just before? (cause 1)
- Rate and extrapolation: when would it reach the module's limit at this rate? **(to confirm: limits per sensor)**

## Fix / mitigation
- Watch; record rate and start time. The assistant does not know the safe limits yet. **(to confirm)**

## Escalation
If the extrapolated time to a limit is short, call the camera expert. **(to confirm: limits and who)**

## History
- Lab (P-13 to P-15): drifts of 6 °C/h and 1.5 °C/h on single modules detected; the shared ambient wave did not trigger.
