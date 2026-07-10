"""The per-run manifest handed to the downstream ingestion program.

A manifest is one JSONL file per run listing the run's delta records — the
files it added or changed — each with the file's path relative to ``dir``, its
``action`` (``added``/``changed``), station, day, and the listing's
last-modified and size. It is always written, even when empty, so downstream can
rely on its presence as the signal a run completed.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class DeltaRecord:
    """One line of the manifest: a file the run added or changed."""

    path: str
    action: str
    station: str
    day: str
    last_modified: str
    size: str


def write_manifest(path: Path, records: list[DeltaRecord]) -> None:
    """Write ``records`` to ``path`` as JSONL; an empty file when there are none."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(asdict(record)))
            handle.write("\n")
