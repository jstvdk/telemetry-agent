"""The read-only tools. Registered once here; the agent and the MCP server both use this list.

Principles (03-architecture §4): features, not raw series; short summaries first, detail on
demand; every item carries the handle the answer must cite (event ID, runbook ID, log ref).
"""

from collections import Counter
from datetime import datetime
from typing import Annotated, Any, Literal

import numpy as np
from pydantic import Field

from shiftassist.collect.model import LEVELS
from shiftassist.collect.summary import template
from shiftassist.detect.model import Event
from shiftassist.sim.records import EventKind
from shiftassist.tools.registry import tool
from shiftassist.tools.snapshot import Snapshot

Iso = Annotated[
    str | None, Field(description="ISO-8601 UTC time, e.g. 2026-09-28T21:40:00Z. Optional.")
]
Since = Annotated[
    float | None,
    Field(
        description="Instead of start: the last N minutes before `end` (or before the newest data)."
    ),
]
Level = Literal["DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"]
SEVERITY = {"info": 0, "warning": 1, "alarm": 2}
RAW_TEXT_CHARS = 1500


def _iso(t: datetime | None) -> str | None:
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z") if t else None


def _brief(e: Event) -> dict[str, Any]:
    return {
        "id": e.event_id,
        "ts": _iso(e.ts),
        "end": _iso(e.end),
        "kind": e.kind,
        "severity": e.severity,
        "subsystem": e.subsystem,
        "entity": e.entity,
        "channel": e.channel,
        "summary": e.summary,
    }


def _unit_name(unit: str) -> str:
    return unit if unit.endswith(".service") else f"sstcam-{unit}.service"


@tool()
def query_timeline(
    snap: Snapshot,
    start: Iso = None,
    end: Iso = None,
    since_minutes: Since = None,
    subsystem: Annotated[
        str | None, Field(description="e.g. chiller, slowsignal, gatherer")
    ] = None,
    kind: Annotated[EventKind | None, Field(description="Only this event kind.")] = None,
    min_severity: Literal["info", "warning", "alarm"] = "info",
    limit: Annotated[int, Field(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    """List the detector's events (the timeline) in a time window, oldest first.

    Start most investigations here. Events are written by deterministic rules, never by a model;
    each has an ID (EV-…) that answers must cite. Without a window, the whole snapshot is used.
    """
    a, b = snap.window(start, end, since_minutes)
    hits = [
        e
        for e in snap.events
        if a <= e.ts <= b
        and (subsystem is None or e.subsystem == subsystem)
        and (kind is None or e.kind == kind)
        and SEVERITY[e.severity] >= SEVERITY[min_severity]
    ]
    return {
        "camera": snap.camera,
        "window": [_iso(a), _iso(b)],
        "snapshot": [_iso(snap.start), _iso(snap.end)],
        "total": len(hits),
        "events": [_brief(e) for e in hits[:limit]],
    }


@tool(max_output_chars=12000)
def get_event(
    snap: Snapshot, event_id: Annotated[str, Field(description="e.g. EV-000017")]
) -> dict[str, Any]:
    """Full detail of one event: the numbers behind it, the raw journal/log lines it refers to,
    and the runbook entries whose `matches` fit it (with any extra condition in `applies_if`)."""
    e = snap.by_id.get(event_id)
    if e is None:
        raise LookupError(f"no event {event_id!r} in this snapshot")
    ev = dict(e.evidence)
    refs = [*ev.get("refs", []), *(ev[k] for k in ("ref", "first_ref") if k in ev)]
    raw = []
    for r in refs[:12]:
        x = snap.entry(r)
        if x is not None:
            raw.append(
                {
                    "ref": r,
                    "ts": _iso(x.ts),
                    "kind": x.kind,
                    "level": x.level,
                    "process": x.process,
                    "text": x.message[:RAW_TEXT_CHARS],
                }
            )
    return {
        **_brief(e),
        "rule_id": e.rule_id,
        "evidence": ev,
        "raw": raw,
        "runbook": [
            {"id": rb.id, "title": rb.title, "status": rb.status, "applies_if": cond or None}
            for rb, cond in snap.runbook.for_event(e)
        ],
    }


@tool()
def get_unit_history(
    snap: Snapshot,
    unit: Annotated[str, Field(description="Server name (chiller, slowsignal, …) or full unit")],
    start: Iso = None,
    end: Iso = None,
    since_minutes: Since = None,
    limit: Annotated[int, Field(ge=1, le=200)] = 40,
) -> dict[str, Any]:
    """systemd history of one camera server in a window: started / stopped / exited (with exit
    code and status) / restart scheduled, and uncaught tracebacks (which reach only the journal).

    An empty history for a unit whose monitoring stopped means the process did not exit: frozen or
    disconnected, not crashed.
    """
    name = _unit_name(unit)
    known = sorted({e.unit for e in snap.cap.journal if e.unit})
    if name not in known:
        raise LookupError(f"unknown unit {unit!r}; known: {', '.join(known)}")
    a, b = snap.window(start, end, since_minutes)
    items = []
    for x in snap.cap.journal:
        if x.unit != name or not a <= x.ts <= b or x.kind not in ("unit", "traceback"):
            continue
        f = x.fields
        items.append(
            {
                "ref": x.ref,
                "ts": _iso(x.ts),
                "kind": x.kind,
                "event": f.get("event") if x.kind == "unit" else "traceback",
                "exit": f"{f.get('code')}/{f.get('status')}" if f.get("code") else None,
                "text": (f.get("exception_line") or x.message)[:300],
            }
        )
    return {"unit": name, "window": [_iso(a), _iso(b)], "total": len(items), "items": items[:limit]}


@tool()
def search_logs(
    snap: Snapshot,
    start: Iso = None,
    end: Iso = None,
    since_minutes: Since = None,
    process: Annotated[str | None, Field(description="e.g. SLOWSIGNAL-SERVER")] = None,
    min_level: Level = "WARNING",
    contains: Annotated[str | None, Field(description="Case-insensitive substring.")] = None,
    limit: Annotated[int, Field(ge=1, le=100)] = 30,
) -> dict[str, Any]:
    """Camera log entries in a window, with message templates counted (numbers masked).

    A healthy camera logs nothing after start-up, so no entries means nothing was logged, not
    that everything is fine; use monitoring and the unit history for liveness.
    """
    a, b = snap.window(start, end, since_minutes)
    lvl = LEVELS[min_level]
    hits = [
        x
        for x in snap.cap.logs
        if a <= x.ts <= b
        and x.levelno >= lvl
        and (process is None or x.process == process)
        and (contains is None or contains.lower() in x.message.lower())
    ]
    templates = Counter((x.process, x.level, template(x.message)) for x in hits)
    return {
        "window": [_iso(a), _iso(b)],
        "total": len(hits),
        "templates": [
            {"process": p, "level": lv, "template": t[:200], "count": n}
            for (p, lv, t), n in templates.most_common(15)
        ],
        "entries": [
            {
                "ref": x.ref,
                "ts": _iso(x.ts),
                "level": x.level,
                "process": x.process,
                "text": x.message[:400],
            }
            for x in hits[:limit]
        ],
    }


def _slope_per_h(t: np.ndarray, y: np.ndarray) -> float | None:
    if len(t) < 3:
        return None
    x = (t - t[0]) / 3600.0
    xm = x - x.mean()
    sxx = float(xm @ xm)
    return float(xm @ (y - y.mean())) / sxx if sxx else None


@tool()
def get_telemetry_features(
    snap: Snapshot,
    subsystem: Annotated[str, Field(description="chiller, slowboard, slowsignal, eventbuilder")],
    channel: Annotated[str, Field(description="e.g. supply_temperature, temperature_sipm3")],
    entity: Annotated[
        str | None, Field(description="Slow-signal module, e.g. tm07; omit for others")
    ] = None,
    start: Iso = None,
    end: Iso = None,
    since_minutes: Since = None,
) -> dict[str, Any]:
    """Features of one monitoring channel in a window, not raw samples: count, first/last, mean,
    min, max, slope per hour, longest silence, and the baseline's normal slope spread (sigma) so
    the slope can be judged. For a slow-signal module, also the slope relative to the other
    modules (shared ambient changes removed), which is what the trend rule uses."""
    key = (subsystem, entity or "", channel)
    s = snap.series.get(key)
    if s is None:
        options = sorted({k[2] for k in snap.series if k[0] == subsystem})
        if not options:
            subs = sorted({k[0] for k in snap.series})
            raise LookupError(f"no monitoring for subsystem {subsystem!r}; have: {subs}")
        ents = sorted({k[1] for k in snap.series if k[0] == subsystem and k[1]})
        hint = f"; entities: {ents[:40]}" if ents else ""
        raise LookupError(
            f"no channel {channel!r} for {subsystem} {entity or ''}: {options[:60]}{hint}"
        )
    a, b = snap.window(start, end, since_minutes)
    lo, hi = np.searchsorted(s.t, a.timestamp()), np.searchsorted(s.t, b.timestamp(), "right")
    t, y = s.t[lo:hi], s.y[lo:hi]
    edges = np.concatenate([[a.timestamp()], t, [b.timestamp()]])
    out: dict[str, Any] = {
        "subsystem": subsystem,
        "entity": entity,
        "channel": channel,
        "window": [_iso(a), _iso(b)],
        "n": len(t),
        "longest_silence_s": round(float(np.diff(edges).max()), 1),
    }
    if len(t):
        out |= {
            "first": float(y[0]),
            "last": float(y[-1]),
            "mean": float(y.mean()),
            "min": float(y.min()),
            "max": float(y.max()),
            "slope_per_h": _slope_per_h(t, y),
        }
    r = snap.residuals.get(key)
    if r is not None:
        m = (r.t >= a.timestamp()) & (r.t <= b.timestamp())
        out["relative_slope_per_h"] = _slope_per_h(r.t[m], r.y[m])
    tp = snap.profile.trend.get(f"{subsystem}/{channel}") if snap.profile else None
    if tp is not None:
        out["baseline"] = {
            "slope_sigma_per_h": tp.sigma_per_h,
            "trend_threshold_per_h": tp.threshold_per_h,
            "window_s": snap.profile.params.trend_window_s if snap.profile else None,
            "on_relative_slope": tp.residual,
        }
    return out


@tool()
def search_runbook(
    snap: Snapshot,
    query: Annotated[str, Field(description="Symptom, message or component, in plain words")],
    limit: Annotated[int, Field(ge=1, le=10)] = 3,
) -> dict[str, Any]:
    """Keyword search of the runbook. Returns entry IDs, titles, status and the Symptom section;
    read a whole entry with get_runbook_entry. Entries with status `ai-draft` have not been
    checked by an operator: cite them, but say they are drafts. If nothing fits, say the
    situation is not in the runbook rather than inventing a procedure."""
    return {
        "results": [
            {
                "id": e.id,
                "title": e.title,
                "status": e.status,
                "score": round(sc, 2),
                "symptom": e.sections.get("Symptom", "")[:600],
            }
            for e, sc in snap.runbook.search(query, limit)
        ]
    }


@tool(max_output_chars=10000)
def get_runbook_entry(
    snap: Snapshot, entry_id: Annotated[str, Field(description="e.g. RB-005")]
) -> dict[str, Any]:
    """One runbook entry in full: status, sources and every section (Meaning, Likely causes,
    Checks, Fix / mitigation, Escalation, History). Steps marked '(to confirm)' are proposals
    no operator has approved."""
    e = snap.runbook.entries.get(entry_id)
    if e is None:
        raise LookupError(f"no runbook entry {entry_id!r}; have {sorted(snap.runbook.entries)}")
    return {"id": e.id, "title": e.title, "status": e.status, "sources": e.sources, **e.sections}
