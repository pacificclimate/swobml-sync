"""Compute the delta: which of a station's files a run must download.

A file is part of the delta when it is absent from sync state (**added**) or
when its ``(last-modified, size)`` in the listing differs from what state
records (**changed** — an upstream correction). Everything else is already
downloaded and skipped. This is the pure heart of change detection (ADR 0002);
it touches neither the network nor the filesystem.
"""

from __future__ import annotations

from dataclasses import dataclass

from swobml_sync.listing import Entry
from swobml_sync.state import StationState

ADDED = "added"
CHANGED = "changed"


@dataclass(frozen=True)
class Delta:
    """One file to download, tagged with why (``ADDED`` or ``CHANGED``)."""

    entry: Entry
    action: str


def station_deltas(entries: list[Entry], known: StationState) -> list[Delta]:
    """The deltas among ``entries`` (a station's files) given its ``known`` state."""
    deltas: list[Delta] = []
    for entry in entries:
        record = known.get(entry.name)
        if record is None:
            deltas.append(Delta(entry=entry, action=ADDED))
        elif record.get("mtime") != entry.last_modified or record.get("size") != entry.size:
            deltas.append(Delta(entry=entry, action=CHANGED))
    return deltas
