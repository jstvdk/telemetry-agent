---
id: RB-004
title: One slow-signal module stops reporting
status: ai-draft
verified_by:
verified_on:
components: [slowsignal, TARGET module]
matches:
  - {kind: gap, subsystem: slowsignal, entity: "tm*"}
sources:
  - P-12 (slow-signal monitoring is one message per TARGET module per second, identified by tm_slot)
  - P-13 (lab: module 5 silent 2 min → 122 s gap; the other 31 modules normal)
  - R18 (slow-signal log messages do not name the module)
---
## Symptom
One module (e.g. `tm07`) stops sending slow-signal monitoring while the other modules continue.

## Meaning
The slow-signal server is running (the other modules report). The problem is local to one module or its path to the server.

## Likely causes
1. **The module lost power or was switched off** (slowboard controls TARGET module power).
2. **Communication with that module failed** (cable, connector, module firmware).
3. **The module is not selected / not configured** after a configuration change.

## Checks
- Is the module's power on? `sstcam slowboard read-target-module-power`. **(untested in the lab)**
- Did a configuration change or restart happen just before? (journal, config snapshot in the run directory)
- Is it the same module as in earlier incidents? (history of this entry)
- Several modules at once: if they start within seconds on most modules, the whole slow-signal server is the problem (RB-001).

## Fix / mitigation
- Do not power-cycle modules without the electronics expert. **(to confirm)**
- Record the module ID and time in the shift log; if the module comes back by itself, note the duration.

## Escalation
Electronics / camera expert if the module does not come back, or if it happens repeatedly. **(to confirm: who, and whether observation can continue with one module missing)**

## History
- Lab (P-13, P-15): a module silenced for 2 min was detected as a 1-module gap within seconds; no log line mentioned it.
