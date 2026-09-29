---
id: RB-009
title: Chiller temperatures change
status: ai-draft
verified_by:
verified_on:
components: [chiller, cooling]
matches:
  - {kind: trend, subsystem: chiller}
  - {kind: trend, subsystem: slowsignal, entity: null, rule: R-TRD-02}
sources:
  - 'sstcam-telecom/sstcam_telecom/protobuf/chiller/v1alpha1/telemetry.proto:6-27 (supply/return/heater/heat-exchanger temperatures, setpoints, is_running, fault and flow flags)'
  - 'P-13 (lab: supply temperature ramp 23 → 30 °C seen at +67 °C/h, all four chiller temperatures moved)'
---
## Symptom
Chiller temperatures (supply, return, heater, heat exchanger) rise or fall faster than normal. Possibly followed, minutes later, by all camera modules warming together (a camera-wide trend).

## Meaning
The camera's cooling is not holding its temperature. Module temperatures follow with a delay.

## Likely causes
1. **The setpoint was changed** (deliberately or by mistake). `temperature_setpoint` changes at the start.
2. **The chiller cannot hold the setpoint**: a fault (compressor `system1_fault`/`system2_fault`, `pump_fault`), low coolant level (`level_indicator`), low flow (`flow_indicator`, `flow_rate`), or it stopped (`is_running` false).
3. **Heat load or ambient changed** (sun on the enclosure, a door open). Slow, and setpoint and fault flags unchanged.

## Checks
- `temperature_setpoint` before and after the start of the change.
- Fault and flow flags, `is_running`, `flow_rate` at the same time.
- Direction and rate; do the camera modules follow (camera-wide trend event)?

## Fix / mitigation
- Cause 1: if the change was not planned, report it; do not change the setpoint yourself. **(to confirm)**
- Cause 2: follow the chiller's own procedure. **(to confirm: where is it)**

## Escalation
Cooling expert if a fault flag is set or the supply temperature keeps rising. **(to confirm: limits and who)**

## History
- Lab (P-13, P-15): mock supply-temperature ramp; setpoint unchanged; all four temperatures moved.
