"""Tests for the per-run JSONL manifest."""

from __future__ import annotations

import json
from pathlib import Path

from swobml_sync.manifest import DeltaRecord, write_manifest


def _rec(path: str, action: str) -> DeltaRecord:
    return DeltaRecord(
        path=path,
        action=action,
        station="kenn",
        day="20260710",
        last_modified="2026-07-10 01:50",
        size="3.3K",
    )


def test_manifest_written_one_json_object_per_line(tmp_path: Path) -> None:
    path = tmp_path / "m.jsonl"
    records = [_rec("a/b/x.xml", "added"), _rec("a/b/y.xml", "changed")]
    write_manifest(path, records)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first == {
        "path": "a/b/x.xml",
        "action": "added",
        "station": "kenn",
        "day": "20260710",
        "last_modified": "2026-07-10 01:50",
        "size": "3.3K",
    }


def test_empty_manifest_is_still_written(tmp_path: Path) -> None:
    path = tmp_path / "empty.jsonl"
    write_manifest(path, [])
    assert path.exists()
    assert path.read_text(encoding="utf-8") == ""


def test_manifest_creates_parent_directory(tmp_path: Path) -> None:
    path = tmp_path / "manifests" / "run.jsonl"
    write_manifest(path, [])
    assert path.exists()
