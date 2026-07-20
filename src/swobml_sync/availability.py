"""Discover what the server still holds, and gate the run against it.

The availability window used to be a guess (the hard-coded 65 of ADR 0001). It
is really a *sliding* two-sided window: the live root index lists only the day
directories the server currently offers, and that set moves forward each day.
One cheap discovery request per run learns the real ``[earliest … latest]`` span
(see ADR 0004), which then drives two things:

*The input gate.* A day the user **explicitly named** — every ``--date`` value
and the ``--as-of`` anchor — that lies outside the window is a hard failure
before any listing, at either edge: we cannot make an expired day come back, and
a future day beyond ``latest`` cannot be delivered either. A day merely swept in
by a long ``--days-back`` tail reaching past ``earliest`` is instead dropped with
one warning and the rest of the window syncs — the lookback spilling one day past
the edge is expected, not an error. Dropped days are never listed, so ticket-04's
failure/exit accounting never counts a provably-gone day as a download failure.

*Dynamic retention.* The discovered horizon replaces the fixed 65 for automatic
purge (see :mod:`swobml_sync.housekeeping`).

Two deliberate failure tiers (ADR 0004): a root index that will not fetch or
holds **zero** valid day directories aborts the whole run (:class:`DiscoveryError`,
Tier 1) rather than syncing blindly against an always-on server; a valid index
that simply lacks the current UTC day proceeds with the sync and gate but skips
automatic purge (Tier 2, handled by the caller — a missing "today" is legitimate
very early in a UTC day).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime

from swobml_sync import layout
from swobml_sync.client import HttpClient
from swobml_sync.listing import directories, parse_index

log = logging.getLogger("swobml_sync")


class DiscoveryError(Exception):
    """Tier 1: the availability window could not be discovered — abort the run.

    Raised when the root index fetch fails (any error, including a ``404``) or the
    index parses but contains no valid ``YYYYMMDD`` directories. A total discovery
    failure against a fixed, always-on server is alarming enough to stop before
    doing any sync work rather than sync blindly.
    """


class GateError(Exception):
    """An explicitly-named day lies outside the available window (or nothing is
    left to sync) — abort before listing any day."""


@dataclass(frozen=True)
class Availability:
    """The ``[earliest … latest]`` day span the server currently offers.

    Discovered once per run from the root index; the authority for both the input
    gate and the automatic retention horizon.
    """

    earliest: date
    latest: date

    def contains(self, day: date) -> bool:
        """Whether ``day`` falls within the inclusive window."""
        return self.earliest <= day <= self.latest


def _day(value: str) -> date:
    """Parse a validated ``YYYYMMDD`` string to a date (never fails for our input)."""
    return datetime.strptime(value, layout.DAY_FORMAT).date()


def _fmt(value: date) -> str:
    return value.strftime(layout.DAY_FORMAT)


def discover(client: HttpClient) -> Availability:
    """Fetch and parse the root index into the ``[earliest … latest]`` window.

    Reuses the injected :class:`HttpClient` and the shared ``listing`` parser: the
    availability window is the min/max of the root index's directory entries that
    parse as a ``YYYYMMDD`` day. Raises :class:`DiscoveryError` (Tier 1) when the
    fetch fails or no such directory exists.
    """
    try:
        html = client.get_text(layout.root_url())
    except Exception as exc:  # noqa: BLE001 — any fetch failure is a Tier-1 abort
        raise DiscoveryError(f"root index fetch failed: {exc}") from exc
    days = _parse_day_dirs(html)
    if not days:
        raise DiscoveryError("root index contained no YYYYMMDD day directories")
    window = Availability(earliest=min(days), latest=max(days))
    log.info(
        "availability window [%s … %s] (%d day dir(s))",
        _fmt(window.earliest),
        _fmt(window.latest),
        len(days),
    )
    return window


def _parse_day_dirs(html: str) -> list[date]:
    """The root index's directory entries that parse as a ``YYYYMMDD`` day."""
    parsed: list[date] = []
    for name in directories(parse_index(html)):
        try:
            parsed.append(datetime.strptime(name, layout.DAY_FORMAT).date())
        except ValueError:
            continue  # non-day directories (if any) are not part of the window
    return parsed


def gate(days: list[str], explicit: set[str], window: Availability) -> list[str]:
    """Partition ``days`` against ``window`` before any listing; return the keepers.

    ``explicit`` is the subset of ``days`` the user explicitly named (every
    ``--date`` value, and the ``--as-of`` anchor). The dividing line is explicit
    vs. incidental:

    - An **explicit** day outside the window (too old *or* beyond ``latest``) is a
      hard failure (:class:`GateError`) — silently dropping a day the user pointed
      at would hide that it is gone or unreachable.
    - An **incidental** ``--days-back`` tail day older than ``earliest`` is dropped
      (never listed) and named in one warning; the tail only ever runs older than
      the anchor, so it can only cross the lower edge.
    - Any other day (inside the window, or an incidental day newer than ``latest``
      — a Tier-2 "today" not yet in the index) is kept and listed.

    Raises :class:`GateError` if any explicit day is out of range, or if nothing
    survives the partition (a run with nothing left to do).
    """
    kept: list[str] = []
    dropped: list[str] = []
    failed: list[str] = []
    for day in days:
        parsed = _day(day)
        if window.contains(parsed):
            kept.append(day)
        elif day in explicit:
            failed.append(day)
        elif parsed < window.earliest:
            dropped.append(day)
        else:
            # An incidental day newer than `latest` — only ever a Tier-2 "today"
            # missing from the index; keep it so a routine sync still attempts it.
            kept.append(day)

    span = f"[{_fmt(window.earliest)} … {_fmt(window.latest)}]"
    if failed:
        raise GateError(
            f"day(s) outside the available window {span}: {', '.join(failed)}"
        )
    if dropped:
        log.warning(
            "dropping %d day(s) older than the earliest available %s: %s",
            len(dropped),
            _fmt(window.earliest),
            ", ".join(dropped),
        )
    if not kept:
        raise GateError(f"no requested day is within the available window {span}")
    return kept
