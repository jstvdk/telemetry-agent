# ADR-0008 · SQLite as the event timeline and snapshot format

**Status:** Accepted

## Context
Tools need history ("what happened in the last hour?"), not just the live stream. Evaluation needs a frozen copy of the data. The demo must run with zero infrastructure.

## Decision
- One SQLite file per run with `raw_messages`, `telemetry` and `events` tables ([03 §3](../03-architecture.md#3-data-model-sqlite)).
- WAL mode: the collector writes while tools read.
- A **snapshot** is a copy of the file. "Now" in every tool is the newest timestamp in the snapshot, so time-relative questions have fixed answers.
- The DB path is a config value, never hard-coded, so eval runs can point at snapshots.

## Consequences
- Zero setup; snapshots are easy to version and share (small synthetic ones can be committed as test fixtures).
- Not built for heavy telemetry analytics at production volume. **DuckDB** is the upgrade path, with the same queries behind the store module.

## Alternatives rejected
- **Time-series DB (InfluxDB, TimescaleDB):** right for production telemetry, too heavy for a demo and for fixture snapshots.
- **Reading the stream directly:** no history, no reproducibility.
