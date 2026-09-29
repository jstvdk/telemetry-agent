"""The runbook as the LLM layer sees it: entries with status, sections, and ``matches``.

Two ways in:
- ``for_event``: deterministic. An entry's ``matches`` block says which detector events it is
  about; this is how the assistant finds the entry for an event without guessing.
- ``search``: keyword ranking (BM25) over the entry text, for questions that do not start from an
  event.

``matches`` semantics (all given keys must hold; lists mean "any of"):
  kind       event kind
  subsystem  event subsystem
  entity     null → the event has no entity; a glob ("tm*") → the entity matches
  channel    event channel
  rule       event rule_id
  template   glob on the event's ``evidence.signature`` (new_signature events)
Other keys (``simultaneous``, ``from_start``) describe the symptom for humans and are not checked.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

import yaml

from shiftassist.detect.model import Event

CHECKED_KEYS = {"kind", "subsystem", "entity", "channel", "rule", "template"}


@dataclass(frozen=True)
class Entry:
    id: str
    title: str
    status: str  # ai-draft | verified | obsolete
    path: str
    matches: list[dict[str, Any]]
    sources: list[str]
    sections: dict[str, str]  # heading -> text
    front: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n\n".join(f"## {h}\n{t}" for h, t in self.sections.items())


def parse_entry(path: Path) -> Entry:
    raw = path.read_text()
    _, front_text, body = raw.split("---", 2)
    front = yaml.safe_load(front_text)
    sections: dict[str, str] = {}
    for block in re.split(r"^## ", body, flags=re.M)[1:]:
        head, _, text = block.partition("\n")
        sections[head.strip()] = text.strip()
    return Entry(
        id=front["id"],
        title=front["title"],
        status=front["status"],
        path=path.name,
        matches=front.get("matches") or [],
        sources=[str(s) for s in front.get("sources") or []],
        sections=sections,
        front=front,
    )


def _any(value: Any, want: Any, glob: bool = False) -> bool:
    options = want if isinstance(want, list) else [want]
    if glob:
        return value is not None and any(fnmatchcase(str(value), str(o)) for o in options)
    return value in options


def matches(m: dict[str, Any], ev: Event) -> bool:
    if "kind" in m and not _any(ev.kind, m["kind"]):
        return False
    if "subsystem" in m and not _any(ev.subsystem, m["subsystem"]):
        return False
    if "entity" in m:
        if m["entity"] is None:
            if ev.entity is not None:
                return False
        elif not _any(ev.entity, m["entity"], glob=True):
            return False
    if "channel" in m and not _any(ev.channel, m["channel"]):
        return False
    if "rule" in m and not _any(ev.rule_id, m["rule"]):
        return False
    return not (
        "template" in m and not _any(ev.evidence.get("signature"), m["template"], glob=True)
    )


_WORD = re.compile(r"[a-z0-9_]+")


def tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower().replace("-", "_"))


class Runbook:
    def __init__(self, entries: list[Entry]):
        self.entries = {e.id: e for e in entries}
        self._docs = {e.id: Counter(tokens(f"{e.title} {e.title} {e.text}")) for e in entries}
        n = len(entries)
        df: Counter[str] = Counter()
        for c in self._docs.values():
            df.update(c.keys())
        self._idf = {w: math.log(1 + (n - d + 0.5) / (d + 0.5)) for w, d in df.items()}
        self._avg = sum(sum(c.values()) for c in self._docs.values()) / max(n, 1)

    @classmethod
    def load(cls, directory: str | Path) -> "Runbook":
        return cls([parse_entry(p) for p in sorted(Path(directory).glob("RB-*.md"))])

    def for_event(self, ev: Event) -> list[tuple[Entry, dict[str, Any]]]:
        """Entries with a ``matches`` item that fits the event, and that item's unchecked
        conditions (e.g. ``simultaneous: all``): the entry applies only if those hold too."""
        out = []
        for e in self.entries.values():
            fits = [m for m in e.matches if matches(m, ev)]
            if fits:
                advisory = [{k: v for k, v in m.items() if k not in CHECKED_KEYS} for m in fits]
                out.append((e, {} if any(not a for a in advisory) else advisory[0]))
        return out

    def search(self, query: str, limit: int = 3) -> list[tuple[Entry, float]]:
        """BM25 (k1 = 1.2, b = 0.75) over title (counted twice) and sections."""
        q = set(tokens(query))
        scored = []
        for eid, c in self._docs.items():
            length = sum(c.values())
            s = 0.0
            for w in q & c.keys():
                tf = c[w]
                s += self._idf[w] * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * length / self._avg))
            if s > 0:
                scored.append((self.entries[eid], s))
        scored.sort(key=lambda x: -x[1])
        return scored[:limit]
