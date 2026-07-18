"""Orchestrate one run: discover, compute the delta, download, record, report.

Single-partner, over whichever days the run names, and concurrent through one
bounded thread pool sized by ``--workers``. The run is *phased*: it lists every
day's stations, then lists each station's SWOB files to compute the delta
against sync state, then downloads exactly the delta — each phase fanned out
across the same pool. Workers only do network I/O and return values; the main
thread does all the aggregation (recording into state, collecting the manifest,
tallying the summary), so no shared state is mutated concurrently and the
outputs are byte-for-byte identical to a serial run over the same source.

Failures are tolerated so one bad file or listing never loses the run's other
work: transient errors are retried inside the :class:`HttpClient`; an absent day
or station (``404``/:class:`NotFound`) is an empty listing, not a failure; and
anything that still fails is counted, logged, and skipped so successes are
persisted and the run exits non-zero (see the CLI) for the caller to retry.

Each run also logs to a per-run file keyed by its ``runts`` (see
:mod:`swobml_sync.logsetup`) and, at the end, reports hour coverage and purges
everything past the retention horizon (see :mod:`swobml_sync.housekeeping`). The
network lives entirely behind the injected :class:`HttpClient`.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from functools import partial

from swobml_sync import housekeeping, layout, state as state_mod
from swobml_sync.client import HttpClient, NotFound
from swobml_sync.config import Config
from swobml_sync.delta import ADDED, Delta, station_deltas
from swobml_sync.housekeeping import CoverageSummary
from swobml_sync.listing import directories, files, parse_index
from swobml_sync.logsetup import run_log_file
from swobml_sync.manifest import DeltaRecord, write_manifest
from swobml_sync.state import SyncState

log = logging.getLogger("swobml_sync")

_RUNTS_FORMAT = layout.RUNTS_FORMAT
_DAY_FORMAT = layout.DAY_FORMAT


@dataclass
class RunResult:
    """The outcome of a run, mirrored by the stdout summary."""

    manifest: str
    runts: str = ""
    added: int = 0
    changed: int = 0
    failed: int = 0
    days: list[str] = field(default_factory=list)
    coverage: CoverageSummary = field(default_factory=lambda: CoverageSummary(0, 0, 0))


@dataclass(frozen=True)
class _Listing:
    """The outcome of fetching one directory index.

    ``text`` is the index HTML, or ``None`` when the directory is absent
    (``404``) or its listing failed after the client's own retries. ``failed``
    distinguishes those two ``None`` cases: an absent directory is a legitimately
    empty listing, a failed one is counted so the run exits non-zero.
    """

    text: str | None
    failed: bool = False


@dataclass(frozen=True)
class _StationList:
    """A day's discovered stations (phase 1 output)."""

    day: str
    stations: list[str]
    failed: bool


@dataclass(frozen=True)
class _StationDeltas:
    """One station's delta against sync state (phase 2 output)."""

    day: str
    station: str
    deltas: list[Delta]
    failed: bool


@dataclass(frozen=True)
class _Download:
    """The outcome of downloading one delta file (phase 3 output)."""

    day: str
    station: str
    delta: Delta
    failed: bool


def window_days(now: datetime, days_back: int, anchor: date | None = None) -> list[str]:
    """The rolling window as ``YYYYMMDD`` strings: the newest day and the
    previous ``days_back`` days, newest first, all in UTC to match the source
    tree's date partitioning.

    The newest day is ``anchor`` when given (a moveable "today" set by
    ``--as-of``), else ``now``'s UTC date. ``days_back`` always counts backward
    from that newest day.
    """
    newest = anchor if anchor is not None else now.astimezone(timezone.utc).date()
    return [
        (newest - timedelta(days=n)).strftime(_DAY_FORMAT) for n in range(days_back + 1)
    ]


def run(
    config: Config, client: HttpClient, *, now: datetime | None = None
) -> RunResult:
    """Sync ``config``'s days for its partner, returning what changed."""
    now = now or datetime.now(timezone.utc)
    runts = now.strftime(_RUNTS_FORMAT)
    # The whole run logs to a file keyed by runts alongside its manifest, so the
    # log, manifest, and stdout summary all share one correlation key (ticket 06).
    with run_log_file(
        log, layout.log_path(config.directory, config.partner, runts), config.log_level
    ):
        # Explicit --date days replace the window; otherwise the rolling lookback of
        # anchor…anchor-N, where the anchor is --as-of when given, else today. Only
        # these days are listed, delta'd, and merged into state, so untouched days
        # recorded by earlier runs are never re-listed or rewritten.
        if config.days and config.as_of is not None:
            # --date already replaced the window, making --as-of meaningless; say so
            # loudly since --as-of is a specific, intentful request being dropped.
            log.warning("--as-of %s ignored because --date was given", config.as_of)
        anchor = (
            datetime.strptime(config.as_of, _DAY_FORMAT).date()
            if config.as_of is not None
            else None
        )
        days = list(config.days) or window_days(now, config.days_back, anchor)

        state = state_mod.load(layout.state_path(config.directory, config.partner))
        result = RunResult(manifest="", runts=runts, days=days)
        records = _run_phases(config, client, days, state, result)

        # End-of-run housekeeping over the post-download state: report each
        # station's hour coverage (aggregate into the summary), then purge state
        # entries and run files past the retention horizon before state is saved,
        # so the purged days are not re-persisted (ticket 07).
        result.coverage = housekeeping.report_coverage(state, days)
        housekeeping.purge(
            state,
            config.directory,
            config.partner,
            now.astimezone(timezone.utc).date(),
            config.retention_days,
        )

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


def _run_phases(
    config: Config,
    client: HttpClient,
    days: list[str],
    state: SyncState,
    result: RunResult,
) -> list[DeltaRecord]:
    """Run the three phases through one bounded pool and aggregate the outcome.

    Phases run in order (all discovery before any download); within a phase the
    work fans out across the pool. Every phase preserves its input order, so the
    downloads — and therefore sync-state writes, the manifest, and the summary —
    come out in the same day → station → file order a serial run would produce.
    """
    partner = config.partner
    with ThreadPoolExecutor(max_workers=config.workers) as pool:
        # Phase 1 — list each day's stations.
        station_lists = pool.map(partial(_list_stations, client, partner), days)
        day_stations: list[tuple[str, str]] = []
        for listed in station_lists:
            if listed.failed:
                result.failed += 1
            day_stations.extend((listed.day, station) for station in listed.stations)

        # Phase 2 — list each station's files and compute its delta against state.
        station_deltas_out = pool.map(
            partial(_list_station_files, client, config, state), day_stations
        )
        pending: list[tuple[str, str, Delta]] = []
        for out in station_deltas_out:
            if out.failed:
                result.failed += 1
            pending.extend((out.day, out.station, delta) for delta in out.deltas)

        # Phase 3 — download exactly the delta.
        downloads = list(pool.map(partial(_download, client, config), pending))

    return _record_downloads(config, downloads, state, result)


def _list_index(client: HttpClient, url: str, label: str) -> _Listing:
    """Fetch a directory index, classifying absence vs. permanent failure.

    This is the one place the 404-as-empty-vs-permanent-failure policy lives, so
    days and stations can't drift apart: a ``404`` (:class:`NotFound`) is an empty
    listing and not counted; any other error after the client's own retries is
    logged and flagged ``failed`` so the caller counts it and the run exits
    non-zero. Either way the caller skips that day or station rather than aborting.
    """
    try:
        return _Listing(client.get_text(url))
    except NotFound:
        log.info("%s: absent upstream, treating as empty", label)
        return _Listing(None)
    except Exception as exc:  # noqa: BLE001 — a bad listing must not abort the run
        log.error("%s: listing failed, skipping: %s", label, exc)
        return _Listing(None, failed=True)


def _list_stations(client: HttpClient, partner: str, day: str) -> _StationList:
    """Phase 1: discover a day's stations from its directory index."""
    listing = _list_index(client, layout.day_url(partner, day), f"day {day}")
    if listing.text is None:
        return _StationList(day, [], listing.failed)
    stations = directories(parse_index(listing.text))
    log.info("day %s: %d station(s)", day, len(stations))
    return _StationList(day, stations, False)


def _list_station_files(
    client: HttpClient, config: Config, state: SyncState, day_station: tuple[str, str]
) -> _StationDeltas:
    """Phase 2: list one station's SWOB files and delta them against state.

    Reads ``state`` but never mutates it — state is written only by the main
    thread after every download, so these concurrent reads are safe.
    """
    day, station = day_station
    url = layout.station_url(config.partner, day, station)
    listing = _list_index(client, url, f"station {day}/{station}")
    if listing.text is None:
        return _StationDeltas(day, station, [], listing.failed)
    entries = files(parse_index(listing.text))
    known = state.get(day, {}).get(station, {})
    return _StationDeltas(day, station, station_deltas(entries, known), False)


def _download(
    client: HttpClient, config: Config, pending: tuple[str, str, Delta]
) -> _Download:
    """Phase 3: download one delta file, tolerating a single file's failure.

    A file that still fails after the client's retries is logged and marked
    ``failed`` so the main thread leaves it out of state and the manifest; the
    next run retries it while the rest of this run proceeds.
    """
    day, station, delta = pending
    entry = delta.entry
    url = layout.file_url(config.partner, day, station, entry.name)
    dest = layout.local_file_path(
        config.directory, config.partner, day, station, entry.name
    )
    try:
        client.download(url, dest)
    except Exception as exc:  # noqa: BLE001 — one bad file must not fail the run
        log.warning("download failed %s: %s", url, exc)
        return _Download(day, station, delta, failed=True)
    return _Download(day, station, delta, failed=False)


def _record_downloads(
    config: Config,
    downloads: list[_Download],
    state: SyncState,
    result: RunResult,
) -> list[DeltaRecord]:
    """Merge each successful download into state, the manifest, and the summary.

    Runs on the main thread over the phase-3 results in listing order, so it is
    the sole writer of sync state and the manifest — no locking needed, and the
    output ordering matches a serial run.
    """
    records: list[DeltaRecord] = []
    for dl in downloads:
        if dl.failed:
            result.failed += 1
            continue
        entry = dl.delta.entry
        mtime = entry.last_modified or ""
        size = entry.size or ""
        state_mod.record(state, dl.day, dl.station, entry.name, mtime, size)
        records.append(
            DeltaRecord(
                path=layout.relative_file_path(
                    config.partner, dl.day, dl.station, entry.name
                ),
                action=dl.delta.action,
                station=dl.station,
                day=dl.day,
                last_modified=mtime,
                size=size,
            )
        )
        if dl.delta.action == ADDED:
            result.added += 1
        else:
            result.changed += 1
        log.info("%s %s", dl.delta.action, entry.name)
    return records
