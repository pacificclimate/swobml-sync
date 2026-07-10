"""Tests for computing a station's delta against sync state."""

from __future__ import annotations

from swobml_sync.delta import ADDED, CHANGED, station_deltas
from swobml_sync.listing import Entry


def _file(name: str, mtime: str, size: str) -> Entry:
    return Entry(name=name, is_dir=False, last_modified=mtime, size=size)


def test_absent_file_is_added() -> None:
    entries = [_file("a.xml", "2026-07-10 01:50", "3.3K")]
    deltas = station_deltas(entries, known={})
    assert [(d.entry.name, d.action) for d in deltas] == [("a.xml", ADDED)]


def test_unchanged_file_is_skipped() -> None:
    entries = [_file("a.xml", "2026-07-10 01:50", "3.3K")]
    known = {"a.xml": {"mtime": "2026-07-10 01:50", "size": "3.3K"}}
    assert station_deltas(entries, known=known) == []


def test_changed_mtime_is_changed() -> None:
    entries = [_file("a.xml", "2026-07-10 09:00", "3.3K")]
    known = {"a.xml": {"mtime": "2026-07-10 01:50", "size": "3.3K"}}
    deltas = station_deltas(entries, known=known)
    assert [(d.entry.name, d.action) for d in deltas] == [("a.xml", CHANGED)]


def test_changed_size_is_changed() -> None:
    entries = [_file("a.xml", "2026-07-10 01:50", "4.0K")]
    known = {"a.xml": {"mtime": "2026-07-10 01:50", "size": "3.3K"}}
    deltas = station_deltas(entries, known=known)
    assert deltas[0].action == CHANGED


def test_mixed_batch_partitions_correctly() -> None:
    entries = [
        _file("a.xml", "m1", "1K"),  # unchanged
        _file("b.xml", "m2-new", "1K"),  # changed
        _file("c.xml", "m3", "1K"),  # added
    ]
    known = {"a.xml": {"mtime": "m1", "size": "1K"}, "b.xml": {"mtime": "m2", "size": "1K"}}
    result = {d.entry.name: d.action for d in station_deltas(entries, known=known)}
    assert result == {"b.xml": CHANGED, "c.xml": ADDED}
