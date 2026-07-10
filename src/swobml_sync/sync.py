"""Orchestrate one run: discover, compute the delta, download, record, report.

This is the walking skeleton (ticket 02): serial, single-partner, over whichever
days the run names. For each day it lists the stations, lists each station's SWOB
files, computes the delta against sync state, downloads exactly the delta,
records each success into state, and collects a manifest record for it. State is
saved once at the end (atomically) and the manifest is always written.

Rolling windows, retries, concurrency, retention, and file logging are later
tickets; the network lives entirely behind the injected :class:`HttpClient`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from swobml_sync import layout, state as state_mod
from swobml_sync.client import HttpClient
from swobml_sync.config import Config
from swobml_sync.delta import ADDED, station_deltas
from swobml_sync.listing import directories, files, parse_index
from swobml_sync.manifest import DeltaRecord, write_manifest
from swobml_sync.state import SyncState

log = logging.getLogger("swobml_sync")

_RUNTS_FORMAT = "%Y%m%dT%H%M%SZ"
_DAY_FORMAT = "%Y%m%d"


@dataclass
class RunResult:
    """The outcome of a run, mirrored by the stdout summary."""

    manifest: str
    added: int = 0
    changed: int = 0
    failed: int = 0
    days: list[str] = field(default_factory=list)


def run(config: Config, client: HttpClient, *, now: datetime | None = None) -> RunResult:
    """Sync ``config``'s days for its partner, returning what changed."""
    now = now or datetime.now(timezone.utc)
    runts = now.strftime(_RUNTS_FORMAT)
    # Explicit --date days when given; otherwise just today. Ticket 03 replaces
    # this fallback with the rolling today…today-N window.
    days = list(config.days) or [now.strftime(_DAY_FORMAT)]

    state = state_mod.load(layout.state_path(config.directory, config.partner))
    records: list[DeltaRecord] = []
    result = RunResult(manifest="", days=days)

    for day in days:
        _sync_day(config, client, day, state, records, result)

    state_mod.save(layout.state_path(config.directory, config.partner), state)

    manifest_path = config.manifest or layout.default_manifest_path(
        config.directory, config.partner, runts
    )
    write_manifest(manifest_path, records)
    result.manifest = str(manifest_path)
    log.info(
        "run %s complete: added=%d changed=%d failed=%d days=%s",
        runts,
        result.added,
        result.changed,
        result.failed,
        ",".join(days),
    )
    return result


def _sync_day(
    config: Config,
    client: HttpClient,
    day: str,
    state: SyncState,
    records: list[DeltaRecord],
    result: RunResult,
) -> None:
    """Discover, delta, download, and record one day for the partner."""
    partner = config.partner
    stations = directories(parse_index(client.get_text(layout.day_url(partner, day))))
    log.info("day %s: %d station(s)", day, len(stations))

    for station in stations:
        station_index = client.get_text(layout.station_url(partner, day, station))
        entries = files(parse_index(station_index))
        known = state.get(day, {}).get(station, {})
        for delta in station_deltas(entries, known):
            entry = delta.entry
            mtime = entry.last_modified or ""
            size = entry.size or ""
            url = layout.file_url(partner, day, station, entry.name)
            dest = layout.local_file_path(config.directory, partner, day, station, entry.name)
            try:
                client.download(url, dest)
            except Exception as exc:  # noqa: BLE001 — one bad file must not fail the run
                result.failed += 1
                log.warning("download failed %s: %s", url, exc)
                continue
            state_mod.record(state, day, station, entry.name, mtime, size)
            records.append(
                DeltaRecord(
                    path=layout.relative_file_path(partner, day, station, entry.name),
                    action=delta.action,
                    station=station,
                    day=day,
                    last_modified=mtime,
                    size=size,
                )
            )
            if delta.action == ADDED:
                result.added += 1
            else:
                result.changed += 1
            log.info("%s %s", delta.action, entry.name)
