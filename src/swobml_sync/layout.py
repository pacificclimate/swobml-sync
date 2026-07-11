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

# Canonical string formats for the two correlation keys that name files in the
# tree: the run timestamp (``runts``) on manifests and logs, and the UTC day on
# source paths. Owned here because this module both builds those names and is the
# neutral place housekeeping parses them back to a date when purging by age.
RUNTS_FORMAT = "%Y%m%dT%H%M%SZ"
DAY_FORMAT = "%Y%m%d"


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


def manifests_dir(directory: Path, partner: str) -> Path:
    """The per-partner directory holding one manifest per run."""
    return directory / partner / "manifests"


def logs_dir(directory: Path, partner: str) -> Path:
    """The per-partner directory holding one log file per run."""
    return directory / partner / "logs"


def default_manifest_path(directory: Path, partner: str, runts: str) -> Path:
    """The default manifest location for a run, keyed by its ``runts``."""
    return manifests_dir(directory, partner) / f"{runts}.jsonl"


def log_path(directory: Path, partner: str, runts: str) -> Path:
    """The per-run log file, keyed by the same ``runts`` as its manifest."""
    return logs_dir(directory, partner) / f"{runts}.log"
