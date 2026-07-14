"""The per-partner flat JSON sync state.

Sync state is the sole source of truth for what "already downloaded" means. It
is one JSON file per partner, keyed ``day -> station -> file -> {mtime, size}``,
loaded whole at startup and rewritten atomically at the end of a run so a killed
run never leaves a torn file (see ADR 0001). A file is recorded here only after
it has downloaded successfully.
"""

from __future__ import annotations

import json
from pathlib import Path

from swobml_sync.atomicio import write_atomic

FileRecord = dict[str, str]
StationState = dict[str, FileRecord]
DayState = dict[str, StationState]
SyncState = dict[str, DayState]


def load(path: Path) -> SyncState:
    """Load sync state from ``path``; an empty state if the file is absent."""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        data: SyncState = json.load(handle)
    return data


def save(path: Path, state: SyncState) -> None:
    """Write ``state`` to ``path`` atomically (temp file + ``os.replace``)."""
    write_atomic(path, json.dumps(state, indent=2, sort_keys=True).encode("utf-8"))


def record(
    state: SyncState,
    day: str,
    station: str,
    file: str,
    mtime: str,
    size: str,
) -> None:
    """Record a successfully downloaded file's change key into ``state``."""
    state.setdefault(day, {}).setdefault(station, {})[file] = {
        "mtime": mtime,
        "size": size,
    }
