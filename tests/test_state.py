"""Tests for loading and atomically saving per-partner sync state."""

from __future__ import annotations

from pathlib import Path

from swobml_sync import state


def test_load_missing_file_is_empty(tmp_path: Path) -> None:
    assert state.load(tmp_path / "nope.json") == {}


def test_save_then_load_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "part" / ".sync-state.json"
    data = {
        "20260710": {"kenn": {"a.xml": {"mtime": "2026-07-10 01:50", "size": "3.3K"}}}
    }
    state.save(path, data)
    assert state.load(path) == data


def test_save_creates_parent_directories(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "nested" / ".sync-state.json"
    state.save(path, {})
    assert path.exists()


def test_save_is_atomic_leaving_no_temp_file(tmp_path: Path) -> None:
    path = tmp_path / ".sync-state.json"
    state.save(path, {"20260710": {}})
    siblings = list(path.parent.iterdir())
    assert siblings == [path]


def test_record_inserts_nested_file_entry() -> None:
    data: state.SyncState = {}
    state.record(data, "20260710", "kenn", "a.xml", "2026-07-10 01:50", "3.3K")
    assert data == {
        "20260710": {"kenn": {"a.xml": {"mtime": "2026-07-10 01:50", "size": "3.3K"}}}
    }


def test_record_second_file_same_station_coexists() -> None:
    data: state.SyncState = {}
    state.record(data, "20260710", "kenn", "a.xml", "m1", "1K")
    state.record(data, "20260710", "kenn", "b.xml", "m2", "2K")
    assert set(data["20260710"]["kenn"]) == {"a.xml", "b.xml"}
