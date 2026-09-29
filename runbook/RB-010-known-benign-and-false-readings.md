---
id: RB-010
title: Known benign messages and known false readings
status: ai-draft
verified_by:
verified_on:
components: [controller, slowsignal, slowboard]
matches:
  - {kind: new_signature, template: "CONTROLLER-SERVER|WARNING|Simulation override is enabled*"}
  - {kind: limit, subsystem: slowsignal, channel: [temperature_i2c_aux, temperature_i2c_primary]}
  - {kind: traceback, subsystem: eventbuilder, summary: "*ZMQError: Address already in use*", with: "once, at start-up, without a restart of the unit"}
  - {kind: new_signature, template: "traceback|sstcam-eventbuilder.service|zmq.error.ZMQError", with: "once, at start-up, without a restart of the unit"}
sources:
  - 'P-23 (lab, B10: event-builder ZMQError "Address already in use" 5 s after boot, no restart, 3 h of normal monitoring afterwards; not seen in B00, B00b, B01)'
  - 'R17 (I2C aux/primary board temperature decoder wrong for every negative value)'
  - 'R15 (flat or impossible mock channels in the lab)'
  - 'P-11 (the controller''s "simulation override" notice is the only WARNING in a clean lab run)'
---
## Symptom
A message or a value that looks alarming but is known not to be a camera problem.

## Known cases
1. **Controller WARNING at start-up: "Simulation override is enabled via CLI flag …".** Written when the controller runs with `--simulated` (lab). Benign in the lab; on a real camera it would mean the controller is simulated, which is itself a problem.
2. **Absurd negative board temperatures** (I2C aux/primary): any negative temperature decodes wrongly, e.g. −5 °C reads as −133 °C or −251 °C (R17). Positive values are right. Expect it on a cold camera (night, cold start). The real temperature is slightly below zero, not −133 °C.
4. **Event-builder `zmq.error.ZMQError: Address already in use (addr='tcp://*:50154')` once at start-up.** An intermittent start-up race inside the event builder (seen in 1 of 4 clean lab boots): the unit does not restart and monitoring is normal afterwards. Benign **only** under those conditions. The same error in a crash loop, or after a restart, means an old process still holds the port: treat as RB-005.
3. **Flat or impossible values from mocked hardware in the lab** (slowboard humidity −25.8 %, external temperature −40 °C, currents and fan speeds 0; R15). Not meaningful; ignore in the lab.

## Checks
- Case 2: other temperatures on the same board plausible and near 0 °C? Then it is the decoder.
- Case 4: did `sstcam-eventbuilder.service` restart, and does event-builder monitoring arrive normally?

## Fix / mitigation
- Case 2: report the decoder bug upstream if not done yet. **(to confirm: tracked where?)**

## Escalation
None, unless a real camera runs with the simulated controller (case 1).

## History
- R17 found by round-tripping the encoders through the server's decoders (P-12).
