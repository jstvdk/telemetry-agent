---
id: RB-007
title: Burst of slow-signal "Hardware error detected" warnings
status: ai-draft
verified_by:
verified_on:
components: [slowsignal, TARGET module, RTD sensors]
matches:
  - {kind: log_burst, subsystem: slowsignal}
  - {kind: new_signature, template: "SLOWSIGNAL-SERVER|WARNING|Hardware error detected:*"}
sources:
  - 'sstcam-slowsignal/sstcam_slowsignal/utils/conversions.py:212 (the warning; fault bits of the SPI temperature word)'
  - 'R18 (the warning names neither module nor sensor; the published temperature stays plausible)'
  - 'R6 (the server does no rate limiting: one warning per bad reading, ~1/s per faulty sensor, and far more with many)'
  - 'P-13 (lab: one faulty RTD → 90 warnings at 0.93/s)'
---
## Symptom
Repeated WARNING lines from the slow-signal server: `Hardware error detected:` followed by one line per fault bit (e.g. `Sensor Hard Fault`, `ADC Out-of-Range`, `Temperature value not valid`).

## Meaning
A temperature sensor (RTD) or its ADC reports a fault in every reading. The temperature published for it is still a plausible number, because the fault bits are masked off before conversion (R18), so the monitoring values alone do not show which sensor is bad. The log line does not say which module either.

## Likely causes
1. **A broken or disconnected RTD** on one module (about one warning per second).
2. **Several sensors or a module-level ADC problem** (rate a multiple of 1/s).
3. **Corrupted packets** (every packet flagged; hundreds per second). In the lab this is the slow-signal mock in `random` mode (R6, R13), not hardware.

## Checks
- Rate of warnings per second: about 1/s → one sensor; N/s → N sensors; hundreds → packet corruption.
- Which fault bits (the continuation lines).
- Did it start with a restart or configuration change?
- The module cannot be located from the logs (R18). **(to confirm: is there an expert tool that reads fault bits per module?)**

## Fix / mitigation
- Note the start time, rate and fault type in the shift log. The camera keeps running.
- The warnings fill the logs (R6): a long burst costs disk space. **(to confirm: acceptable duration before intervening)**

## Escalation
Electronics expert during working hours, unless temperatures are needed for safety interlocks. **(to confirm)**

## History
- Lab (P-13, P-15): one faulty RTD → a burst found by the rate rule; the module could not be identified (R18).
