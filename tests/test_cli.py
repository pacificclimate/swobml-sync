"""Tests for the CLI entry point."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swobml_sync import layout
from swobml_sync.cli import main

# A root index that makes 20260710 (the day these tests request) available, so
# discovery passes and the input gate lets the run proceed.
_ROOT_INDEX = '<pre><a href="20260710/">20260710/</a>  2026-07-10 00:00  -</pre>'


class _StubClient:
    """A client that reports an empty day so ``main`` runs without a network."""

    def get_text(self, url: str) -> str:
        if url == layout.root_url():
            return _ROOT_INDEX
        return "<html><body><pre></pre></body></html>"

    def download(self, url: str, dest: Path) -> None:  # pragma: no cover - never called
        raise AssertionError("empty day should download nothing")


def test_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_main_runs_and_prints_json_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["nb-firewx", str(tmp_path), "--date", "20260710"], client=_StubClient())
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["days"] == ["20260710"]
    assert summary["added"] == 0
    assert Path(summary["manifest"]).exists()
    # The summary carries the run's correlation key, tying it to that run's log
    # and manifest (both keyed by the same runts).
    assert Path(summary["manifest"]).stem == summary["runts"]
    assert (tmp_path / "nb-firewx" / "logs" / f"{summary['runts']}.log").exists()
    # The summary carries an aggregate coverage figure (empty day: zeroes) and
    # never a day-level completeness verdict.
    assert summary["coverage"] == {"station_days": 0, "hours": 0, "possible": 0}


def test_main_errors_without_required_args() -> None:
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code != 0


class _OneFailingFileClient:
    """Lists one station with one file whose download always fails permanently."""

    def get_text(self, url: str) -> str:
        if url == layout.root_url():
            return _ROOT_INDEX
        if url.endswith("kenn/"):
            return '<pre><a href="f.xml">f.xml</a>   2026-07-10 01:50  3.3K</pre>'
        return '<pre><a href="kenn/">kenn/</a>   2026-07-10 01:50    -</pre>'

    def download(self, url: str, dest: Path) -> None:
        raise RuntimeError("permanent download failure")


def test_main_exits_nonzero_when_a_file_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(
        ["nb-firewx", str(tmp_path), "--date", "20260710"],
        client=_OneFailingFileClient(),
    )
    assert rc == 1
    summary = json.loads(capsys.readouterr().out)
    assert summary["failed"] == 1
