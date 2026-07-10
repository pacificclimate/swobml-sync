"""Tests for parsing the Apache directory index into listing entries."""

from __future__ import annotations

from pathlib import Path

from swobml_sync.listing import Entry, directories, files, parse_index

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_day_index_yields_only_station_directories() -> None:
    entries = parse_index(_read("day_index.html"))
    assert directories(entries) == ["eutk", "kenn", "mtwl", "pond", "tahl", "tahw"]
    # The parent-directory and column-sort links are not entries.
    names = [e.name for e in entries]
    assert "Parent Directory" not in names
    assert not any(n.startswith("?") for n in names)


def test_station_index_yields_files_with_mtime_and_size() -> None:
    entries = files(parse_index(_read("station_kenn.html")))
    assert len(entries) == 20
    assert entries[0].name == "2026-07-10-0000-riotinto-kenn-kenn-AUTO-swob.xml"
    first = entries[0]
    assert first.is_dir is False
    assert first.last_modified == "2026-07-10 01:50"
    assert first.size == "3.3K"


def test_directory_entry_has_no_size() -> None:
    entries = parse_index(_read("day_index.html"))
    kenn = next(e for e in entries if e.name == "kenn")
    assert kenn.is_dir is True
    assert kenn.size is None
    assert kenn.last_modified == "2026-07-10 20:49"


def test_empty_listing_yields_no_entries() -> None:
    html = "<html><body><h1>Index of /x</h1><table></table></body></html>"
    assert parse_index(html) == []


def test_entry_is_hashable_value() -> None:
    a = Entry(name="x", is_dir=False, last_modified="m", size="1")
    b = Entry(name="x", is_dir=False, last_modified="m", size="1")
    assert a == b
