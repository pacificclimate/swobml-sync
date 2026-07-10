"""Tests for the CLI entry point."""

from __future__ import annotations

import pytest

from swobml_sync.cli import main


def test_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_main_runs_with_valid_args(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["nb-firewx", "/tmp/whatever"])
    assert rc == 0


def test_main_errors_without_required_args() -> None:
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code != 0
