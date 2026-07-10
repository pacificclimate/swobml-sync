"""URLs on the HPFX server and the local directory tree they sync into.

One place owns the two path shapes so the rest of the program never hand-builds
them. The source URL notably repeats the day twice (see ``notes.md`` and
CONTEXT.md); the local tree is ``{dir}/{partner}/cache/{day}/{station}/{file}``
with per-partner sync state and manifests beside the cache.
"""

from __future__ import annotations

from pathlib import Path

BASE_URL = "https://hpfx.collab.science.gc.ca"

_PARTNERS_SEGMENT = "WXO-DD/observations/swob-ml/partners"


def day_url(partner: str, day: str) -> str:
    """The directory index URL for a partner's day (lists its stations)."""
    return f"{BASE_URL}/{day}/{_PARTNERS_SEGMENT}/{partner}/{day}/"


def station_url(partner: str, day: str, station: str) -> str:
    """The directory index URL for one station's day (lists its SWOB files)."""
    return f"{day_url(partner, day)}{station}/"


def file_url(partner: str, day: str, station: str, file: str) -> str:
    """The URL of a single SWOB file."""
    return f"{station_url(partner, day, station)}{file}"


def relative_file_path(partner: str, day: str, station: str, file: str) -> str:
    """A SWOB file's local path relative to ``dir`` (as recorded in manifests)."""
    return f"{partner}/cache/{day}/{station}/{file}"


def local_file_path(directory: Path, partner: str, day: str, station: str, file: str) -> Path:
    """The absolute local path a SWOB file downloads to."""
    return directory / relative_file_path(partner, day, station, file)


def state_path(directory: Path, partner: str) -> Path:
    """The per-partner flat JSON sync-state file (see ADR 0001)."""
    return directory / partner / ".sync-state.json"


def default_manifest_path(directory: Path, partner: str, runts: str) -> Path:
    """The default manifest location for a run, keyed by its ``runts``."""
    return directory / partner / "manifests" / f"{runts}.jsonl"
