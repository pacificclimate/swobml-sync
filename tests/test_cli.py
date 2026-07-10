"""Tests for the CLI entry point."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swobml_sync.cli import main


class _StubClient:
    """A client that reports an empty day so ``main`` runs without a network."""

    def get_text(self, url: str) -> str:
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


def test_main_errors_without_required_args() -> None:
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code != 0
