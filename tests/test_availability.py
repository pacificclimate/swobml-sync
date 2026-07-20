"""Availability discovery and the input gate, exercised as pure units.

Discovery parses the root index into a two-sided day window; the gate partitions
a resolved day set against that window. Both are network-free — discovery takes a
tiny fake client, the gate takes a plain :class:`Availability` — so the edges
(both failure tiers, explicit vs. incidental days, both window edges) are checked
directly without a full run.
"""

from __future__ import annotations

from datetime import date

import pytest

from swobml_sync import layout
from swobml_sync.availability import (
    Availability,
    DiscoveryError,
    GateError,
    discover,
    gate,
)


def _root_index(days: list[str]) -> str:
    rows = "\n".join(
        f'<a href="{day}/">{day}/</a>  2026-07-10 00:00  -' for day in days
    )
    return f"<html><body><pre>{rows}</pre></body></html>"


class FakeText:
    """A minimal client serving one canned root-index page (or raising)."""

    def __init__(self, html: str | None = None, error: Exception | None = None) -> None:
        self._html = html
        self._error = error

    def get_text(self, url: str) -> str:
        assert url == layout.root_url()
        if self._error is not None:
            raise self._error
        assert self._html is not None
        return self._html

    def download(self, url: str, dest: object) -> None:  # pragma: no cover - unused
        raise AssertionError("discovery never downloads")


# --- discovery ---------------------------------------------------------------


def test_discover_reads_two_sided_window_from_root_index() -> None:
    client = FakeText(_root_index(["20260527", "20260601", "20260718"]))
    window = discover(client)
    assert window == Availability(earliest=date(2026, 5, 27), latest=date(2026, 7, 18))


def test_discover_ignores_non_day_directories() -> None:
    # A real root index carries other directories too; only YYYYMMDD ones count.
    client = FakeText(_root_index(["notes", "20260601", "logs", "20260610"]))
    window = discover(client)
    assert window == Availability(earliest=date(2026, 6, 1), latest=date(2026, 6, 10))


def test_discover_tier1_aborts_when_fetch_fails() -> None:
    client = FakeText(error=RuntimeError("503 exhausted"))
    with pytest.raises(DiscoveryError):
        discover(client)


def test_discover_tier1_aborts_on_zero_day_directories() -> None:
    # A page that parses but holds no YYYYMMDD directory is a total failure too.
    client = FakeText(_root_index(["notes", "logs"]))
    with pytest.raises(DiscoveryError):
        discover(client)


# --- the input gate ----------------------------------------------------------

WINDOW = Availability(earliest=date(2026, 5, 27), latest=date(2026, 7, 18))


def test_gate_keeps_days_inside_the_window() -> None:
    days = ["20260718", "20260601", "20260527"]
    assert gate(days, explicit=set(), window=WINDOW) == days


def test_gate_hard_fails_on_explicit_day_too_old() -> None:
    with pytest.raises(GateError):
        gate(["20260101"], explicit={"20260101"}, window=WINDOW)


def test_gate_hard_fails_on_explicit_future_day() -> None:
    # The upper edge fails too: a named day beyond `latest` cannot be delivered.
    with pytest.raises(GateError):
        gate(["20261231"], explicit={"20261231"}, window=WINDOW)


def test_gate_drops_incidental_tail_below_the_floor_and_keeps_the_rest(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # --as-of 20260528 --days-back 5 → [28,27,26,25,24,23]; 26/25/24/23 fall below
    # the earliest available 20260527 and are incidental (only 28 is named).
    days = ["20260528", "20260527", "20260526", "20260525", "20260524", "20260523"]
    with caplog.at_level("WARNING", logger="swobml_sync"):
        kept = gate(days, explicit={"20260528"}, window=WINDOW)
    assert kept == ["20260528", "20260527"]
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    for dropped in ("20260526", "20260523"):
        assert dropped in warnings[0].getMessage()


def test_gate_keeps_incidental_day_newer_than_latest() -> None:
    # A Tier-2 "today" not yet in the index is incidental (not named), so it is
    # kept and listed rather than dropped — a routine sync must still attempt it.
    days = ["20260719", "20260718"]
    assert gate(days, explicit=set(), window=WINDOW) == days


def test_gate_hard_fails_when_nothing_survives() -> None:
    # An all-incidental set entirely below the floor leaves nothing to do.
    with pytest.raises(GateError):
        gate(["20260101", "20260102"], explicit=set(), window=WINDOW)


def test_gate_silent_when_all_days_inside(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING", logger="swobml_sync"):
        gate(["20260601"], explicit={"20260601"}, window=WINDOW)
    assert [r for r in caplog.records if r.levelname == "WARNING"] == []
