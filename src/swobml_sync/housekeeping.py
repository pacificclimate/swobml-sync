"""End-of-run housekeeping: hour-coverage reporting and retention purge.

Two things happen at the end of every run over the partner's tree.

*Hour coverage.* For each processed day, each station's coverage is how many of
the 24 hourly SWOB files it has (``n/24``), counted straight from post-run sync
state — the sole record of what has actually downloaded — without parsing hours
out of filenames. Per-station coverage goes to the log; an aggregate goes into
the stdout summary. There is deliberately no day-level "complete" verdict (see
CONTEXT.md): stations appear over time and some never publish all 24 hours, so a
per-day percentage would mislead.

*Retention purge.* Anything older than the retention horizon is dropped:
sync-state entries for expired days, and the manifest, log, and stats files whose
``runts`` predates the horizon. Automatic purge derives the horizon from the
server's discovered availability window (:func:`auto_retention_days`), clamped up
to a 30-day floor so a truncated index can never delete recent state; an explicit
``--retention-days`` overrides both discovery and the floor. Purge is by calendar
day relative to the run date and independent of the ``--days-back`` fetch window —
a short window still keeps a long memory. The current run's own files carry the
run date's ``runts`` and so are never in scope. (See ADR 0004; the caller skips
automatic purge entirely on a Tier-2 run whose index is missing today.)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from swobml_sync import layout
from swobml_sync.state import SyncState

log = logging.getLogger("swobml_sync")

HOURS_PER_DAY = 24

# The lowest horizon automatic purge may use, however low discovery comes back:
# automatic purge may delete genuinely ancient state but must never delete state
# newer than this, the primary defence against a truncated index that reports a
# too-recent "earliest" (ADR 0004). An explicit --retention-days bypasses it.
MIN_AUTO_RETENTION_DAYS = 30


@dataclass(frozen=True)
class Coverage:
    """One station's hour coverage for one day: ``hours`` of 24 present."""

    day: str
    station: str
    hours: int


@dataclass(frozen=True)
class CoverageSummary:
    """The run's aggregate coverage across all processed station-days.

    An aggregate only: ``station_days`` station-days together hold ``hours`` of
    ``possible`` (``24 × station_days``) hourly files. No per-day percentage or
    completeness verdict is derived from it (see CONTEXT.md).
    """

    station_days: int
    hours: int
    possible: int


def day_coverages(state: SyncState, days: list[str]) -> list[Coverage]:
    """Each processed day's per-station hour coverage, from post-run state.

    Days follow the run's order; stations within a day are sorted so the report
    is stable. A station appears in state only after a file records against it,
    so every listed station has at least one hour.
    """
    coverages: list[Coverage] = []
    for day in days:
        stations = state.get(day, {})
        for station in sorted(stations):
            # Cap at 24: coverage is "how many of the 24 hourly files" (CONTEXT.md),
            # so the count can never exceed a full day even if state ever held more.
            hours = min(len(stations[station]), HOURS_PER_DAY)
            coverages.append(Coverage(day=day, station=station, hours=hours))
    return coverages


def aggregate(coverages: list[Coverage]) -> CoverageSummary:
    """Roll per-station coverage into one aggregate figure for the summary."""
    station_days = len(coverages)
    return CoverageSummary(
        station_days=station_days,
        hours=sum(c.hours for c in coverages),
        possible=station_days * HOURS_PER_DAY,
    )


def report_coverage(state: SyncState, days: list[str]) -> CoverageSummary:
    """Log each station's ``n/24`` coverage and return the run's aggregate."""
    coverages = day_coverages(state, days)
    for cov in coverages:
        log.info(
            "coverage %s/%s: %d/%d", cov.day, cov.station, cov.hours, HOURS_PER_DAY
        )
    return aggregate(coverages)


def auto_retention_days(run_date: date, earliest_available: date) -> int:
    """The automatic retention horizon: how far back the server still reaches,
    clamped up to :data:`MIN_AUTO_RETENTION_DAYS`.

    ``run_date − earliest_available`` is what discovery says is still retrievable;
    the ``max(…, 30)`` floor is a clamp-up only — automatic purge may delete
    genuinely ancient state but never state newer than the floor, so a truncated
    index reporting a too-recent "earliest" cannot trigger an over-purge.
    """
    discovered = (run_date - earliest_available).days
    return max(discovered, MIN_AUTO_RETENTION_DAYS)


def _horizon(run_date: date, retention_days: int) -> date:
    """The oldest calendar day retained; anything strictly before it is purged."""
    return run_date - timedelta(days=retention_days)


def _expired(when: date | None, horizon: date) -> bool:
    """Whether a parsed date is beyond the horizon; an unparseable ``None`` is not."""
    return when is not None and when < horizon


def _day_date(day: str) -> date | None:
    """Parse a ``YYYYMMDD`` state-day key to a date, or ``None`` if malformed."""
    try:
        return datetime.strptime(day, layout.DAY_FORMAT).date()
    except ValueError:
        return None


def _runts_date(stem: str) -> date | None:
    """Parse a manifest/log file's ``runts`` stem to its date, or ``None`` if foreign."""
    try:
        return datetime.strptime(stem, layout.RUNTS_FORMAT).date()
    except ValueError:
        return None


def purge_state(state: SyncState, run_date: date, retention_days: int) -> list[str]:
    """Drop sync-state entries for days older than the retention horizon.

    Mutates ``state`` in place and returns the purged day keys. Keys that are not
    a valid ``YYYYMMDD`` are left untouched rather than guessed at.
    """
    horizon = _horizon(run_date, retention_days)
    expired = [day for day in state if _expired(_day_date(day), horizon)]
    for day in expired:
        del state[day]
    return expired


def purge_run_files(
    directory: Path, partner: str, run_date: date, retention_days: int
) -> list[Path]:
    """Delete manifest, log, and stats files whose ``runts`` predates the horizon.

    Only files named by a parseable ``runts`` are considered, so a foreign file
    dropped into these directories is never removed. Missing directories (a
    partner that has not written any of them yet) are not an error. Per-run stats
    files (ticket 12) age out on the same horizon as manifests and logs; the
    current run's own ``stats/<runts>.json`` carries today's runts and so is never
    in scope.
    """
    horizon = _horizon(run_date, retention_days)
    removed: list[Path] = []
    for folder in (
        layout.manifests_dir(directory, partner),
        layout.logs_dir(directory, partner),
        layout.stats_dir(directory, partner),
    ):
        if not folder.is_dir():
            continue
        for path in folder.iterdir():
            if path.is_file() and _expired(_runts_date(path.stem), horizon):
                path.unlink()
                removed.append(path)
    return removed


def purge(
    state: SyncState, directory: Path, partner: str, run_date: date, retention_days: int
) -> None:
    """Purge expired state entries and old run files, logging what went."""
    days = purge_state(state, run_date, retention_days)
    files = purge_run_files(directory, partner, run_date, retention_days)
    if days or files:
        log.info(
            "purged %d expired day(s) and %d old run file(s) beyond %d-day retention",
            len(days),
            len(files),
            retention_days,
        )
