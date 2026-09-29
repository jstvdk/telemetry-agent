---
id: RB-012
title: The data disk is full
status: ai-draft
verified_by:
verified_on:
components: [gatherer, slowsignal, data volume]
matches:
  - {kind: traceback, summary: "*No space left on device*"}
  - {kind: new_signature, template: "traceback|*|OSError"}
  - {kind: new_signature, template: "SLOWSIGNAL-SERVER|ERROR|Exception occurred during continuous coroutine*", with: "OSError [Errno 28] tracebacks at the same time"}
sources:
  - 'P-22 (lab, B11: /data filled for 2 min → 8649 gatherer and 238 slow-signal OSError [Errno 28] tracebacks, no exits, all monitoring lost for 120 s)'
  - 'R21 (one partial record left by a failed write makes the rest of the day''s monitoring file unreadable for the project''s reader)'
  - 'sstcam-telecom/sstcam_telecom/protobuf/io.py:26-37 (records appended as 4-byte length + message; no sync marker)'
  - 'sstcam-telecom/sstcam_telecom/protobuf/io.py:309-327 (the reader skips the rest of a file at the first damaged record)'
---
## Symptom
Many `OSError: [Errno 28] No space left on device` tracebacks from the gatherer (one per failed write, dozens per second) and from other servers that write files, while monitoring from every subsystem stops. Slow-signal also logs `Exception occurred during continuous coroutine: uncalib_slowsignal_data_publish` (ERROR), its generic wrapper for the failed write. No server exits or restarts.

## Meaning
The servers keep running, but nothing they produce can be stored. Monitoring written during that time is **lost**, not delayed. When space comes back, recording resumes by itself. A write cut short leaves a partial record in the day's monitoring file, and the project's reader then cannot read anything after it (R21).

## Likely causes
1. **The data volume filled up** (raw data, logs, a runaway file). The traceback flood itself adds to the journal, not to `/data`.
2. **The volume was remounted read-only or lost** (would give `EROFS`/`EIO` instead of `Errno 28`).

## Checks
- `df` on the data volume; the largest recent files. **(to confirm: where raw data goes, and what may be moved)**
- Is recording back? Monitoring resumed and the tracebacks stopped.
- Which monitoring files were being written at the time: they may need the recovery reader (R21).

## Fix / mitigation
- Free space according to the data policy; never delete raw data without permission. **(to confirm)**
- After recovery, record the lost interval in the shift log (monitoring is missing for it).
- Report that the day's monitoring file has a damaged record, so offline analysis uses a reader that resynchronises. **(to confirm: who handles data quality)**

## Escalation
Camera software expert and whoever owns data storage. **(to confirm)**

## History
- Lab (P-22): 2 min full → 120 s of monitoring lost on all sources; one 802-byte partial record at 87.7 % of the file hid the remaining 6489 records from the project's reader.
