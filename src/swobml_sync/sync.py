"""Orchestrate one run: discover, compute the delta, download, record, report.

Serial and single-partner, over whichever days the run names. For each day it
lists the stations, lists each station's SWOB files, computes the delta against
sync state, downloads exactly the delta, records each success into state, and
collects a manifest record for it. State is saved once at the end (atomically)
and the manifest is always written.

Failures are tolerated so one bad file or listing never loses the run's other
work: transient errors are retried inside the :class:`HttpClient`; an absent day
or station (``404``/:class:`NotFound`) is an empty listing, not a failure; and
anything that still fails is counted, logged, and skipped so successes are
persisted and the run exits non-zero (see the CLI) for the caller to retry.

Concurrency, retention, and file logging are later tickets; the network lives
entirely behind the injected :class:`HttpClient`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from swobml_sync import layout, state as state_mod
from swobml_sync.client import HttpClient, NotFound
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


def window_days(now: datetime, days_back: int) -> list[str]:
    """The rolling window as ``YYYYMMDD`` strings: today and the previous
    ``days_back`` days, newest first, all in UTC to match the source tree's
    date partitioning."""
    today = now.astimezone(timezone.utc).date()
    return [(today - timedelta(days=n)).strftime(_DAY_FORMAT) for n in range(days_back + 1)]


def run(config: Config, client: HttpClient, *, now: datetime | None = None) -> RunResult:
    """Sync ``config``'s days for its partner, returning what changed."""
    now = now or datetime.now(timezone.utc)
    runts = now.strftime(_RUNTS_FORMAT)
    # Explicit --date days replace the window; otherwise the rolling lookback of
    # today…today-N. Only these days are listed, delta'd, and merged into state,
    # so untouched days recorded by earlier runs are never re-listed or rewritten.
    days = list(config.days) or window_days(now, config.days_back)

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
    """Discover, delta, download, and record one day for the partner.

    A ``404`` on the day directory means the day does not exist upstream — a
    legitimately empty day, not a failure. Any other listing error is counted so
    the run exits non-zero (and retries next time), but the day is skipped rather
    than aborting the whole run.
    """
    partner = config.partner
    index = _list_or_empty(client, layout.day_url(partner, day), f"day {day}", result)
    if index is None:
        return

    stations = directories(parse_index(index))
    log.info("day %s: %d station(s)", day, len(stations))
    for station in stations:
        _sync_station(config, client, day, station, state, records, result)


def _list_or_empty(client: HttpClient, url: str, label: str, result: RunResult) -> str | None:
    """Fetch a directory index, or ``None`` when it should be treated as empty.

    This is the one place the 404-as-empty-vs-permanent-failure policy lives, so
    days and stations can't drift apart: a ``404`` (:class:`NotFound`) is an empty
    listing and not counted; any other error after the client's own retries is
    counted so the run exits non-zero, logged, and turned into ``None`` so the
    caller skips that day or station rather than aborting the run.
    """
    try:
        return client.get_text(url)
    except NotFound:
        log.info("%s: absent upstream, treating as empty", label)
        return None
    except Exception as exc:  # noqa: BLE001 — a bad listing must not abort the run
        result.failed += 1
        log.error("%s: listing failed, skipping: %s", label, exc)
        return None


def _sync_station(
    config: Config,
    client: HttpClient,
    day: str,
    station: str,
    state: SyncState,
    records: list[DeltaRecord],
    result: RunResult,
) -> None:
    """Delta, download, and record one station's SWOB files.

    Mirrors :func:`_sync_day`'s tolerance: a ``404`` is an empty station, any
    other listing error is counted and the station skipped, and a single file
    that fails after retries is logged and left out of state and the manifest so
    the next run retries it while the rest of the run continues.
    """
    partner = config.partner
    url = layout.station_url(partner, day, station)
    station_index = _list_or_empty(client, url, f"station {day}/{station}", result)
    if station_index is None:
        return

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
