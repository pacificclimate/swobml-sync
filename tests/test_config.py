"""Tests for command-line + environment configuration resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

import pytest

from swobml_sync.config import (
    DEFAULT_DAYS_BACK,
    DEFAULT_LOG_LEVEL,
    DEFAULT_RETENTION_DAYS,
    DEFAULT_WORKERS,
    Config,
    resolve_config,
)


def cfg(argv: Sequence[str], env: Mapping[str, str] | None = None) -> Config:
    return resolve_config(argv, env=env or {})


def test_defaults_with_positionals_only() -> None:
    c = cfg(["nb-firewx", "/data"])
    assert c.partner == "nb-firewx"
    assert c.directory == Path("/data")
    assert c.days_back == DEFAULT_DAYS_BACK == 2
    assert c.days == ()
    assert c.retention_days == DEFAULT_RETENTION_DAYS == 65
    assert c.workers == DEFAULT_WORKERS == 8
    assert c.manifest is None
    assert c.log_level == DEFAULT_LOG_LEVEL == "INFO"


def test_env_fallback_for_positionals() -> None:
    c = cfg([], env={"SWOBML_PARTNER": "on-mto", "SWOBML_DIR": "/srv/data"})
    assert c.partner == "on-mto"
    assert c.directory == Path("/srv/data")


def test_cli_overrides_env_for_positionals_and_flags() -> None:
    c = cfg(
        ["cli-partner", "/cli", "--days-back", "5"],
        env={"SWOBML_PARTNER": "env-partner", "SWOBML_DAYS_BACK": "9"},
    )
    assert c.partner == "cli-partner"
    assert c.directory == Path("/cli")
    assert c.days_back == 5


def test_env_flag_fallback() -> None:
    c = cfg(
        ["p", "/d"],
        env={
            "SWOBML_WORKERS": "16",
            "SWOBML_RETENTION_DAYS": "30",
            "SWOBML_LOG_LEVEL": "debug",
        },
    )
    assert c.workers == 16
    assert c.retention_days == 30
    assert c.log_level == "DEBUG"  # normalised to upper-case


def test_repeated_date_collects_list() -> None:
    c = cfg(["p", "/d", "--date", "20260101", "--date", "20260102"])
    assert c.days == ("20260101", "20260102")


def test_env_date_list_parsed_on_commas_and_spaces() -> None:
    c = cfg(["p", "/d"], env={"SWOBML_DATE": "20260101, 20260102 20260103"})
    assert c.days == ("20260101", "20260102", "20260103")


def test_cli_date_overrides_env_date() -> None:
    c = cfg(["p", "/d", "--date", "20260101"], env={"SWOBML_DATE": "20260202"})
    assert c.days == ("20260101",)


def test_as_of_defaults_to_none() -> None:
    c = cfg(["p", "/d"])
    assert c.as_of is None


def test_as_of_from_cli() -> None:
    c = cfg(["p", "/d", "--as-of", "20260601"])
    assert c.as_of == "20260601"


def test_as_of_from_env() -> None:
    c = cfg(["p", "/d"], env={"SWOBML_AS_OF": "20260601"})
    assert c.as_of == "20260601"


def test_cli_as_of_overrides_env() -> None:
    c = cfg(["p", "/d", "--as-of", "20260601"], env={"SWOBML_AS_OF": "20260101"})
    assert c.as_of == "20260601"


def test_invalid_cli_as_of_errors() -> None:
    with pytest.raises(SystemExit):
        cfg(["p", "/d", "--as-of", "2026-06-01"])


def test_impossible_cli_as_of_errors() -> None:
    with pytest.raises(SystemExit):
        cfg(["p", "/d", "--as-of", "20260231"])  # Feb 31 does not exist


def test_invalid_env_as_of_errors() -> None:
    with pytest.raises(SystemExit):
        cfg(["p", "/d"], env={"SWOBML_AS_OF": "notadate"})


def test_manifest_path_from_cli() -> None:
    c = cfg(["p", "/d", "--manifest", "/tmp/m.jsonl"])
    assert c.manifest == Path("/tmp/m.jsonl")


def test_manifest_path_from_env() -> None:
    c = cfg(["p", "/d"], env={"SWOBML_MANIFEST": "/tmp/env.jsonl"})
    assert c.manifest == Path("/tmp/env.jsonl")


# --- error cases: every invalid input should exit non-zero (SystemExit) ---


def test_missing_partner_and_dir_errors() -> None:
    with pytest.raises(SystemExit):
        cfg([])


def test_missing_dir_errors() -> None:
    with pytest.raises(SystemExit):
        cfg(["only-partner"])


def test_invalid_cli_date_errors() -> None:
    with pytest.raises(SystemExit):
        cfg(["p", "/d", "--date", "2026-01-01"])


def test_impossible_cli_date_errors() -> None:
    with pytest.raises(SystemExit):
        cfg(["p", "/d", "--date", "20260231"])  # Feb 31 does not exist


def test_invalid_env_date_errors() -> None:
    with pytest.raises(SystemExit):
        cfg(["p", "/d"], env={"SWOBML_DATE": "notadate"})


def test_non_int_workers_cli_errors() -> None:
    with pytest.raises(SystemExit):
        cfg(["p", "/d", "--workers", "many"])


def test_non_int_workers_env_errors() -> None:
    with pytest.raises(SystemExit):
        cfg(["p", "/d"], env={"SWOBML_WORKERS": "many"})


def test_zero_workers_errors() -> None:
    with pytest.raises(SystemExit):
        cfg(["p", "/d", "--workers", "0"])


def test_negative_days_back_errors() -> None:
    with pytest.raises(SystemExit):
        cfg(["p", "/d", "--days-back", "-1"])


def test_zero_retention_days_errors() -> None:
    with pytest.raises(SystemExit):
        cfg(["p", "/d", "--retention-days", "0"])


def test_invalid_log_level_errors() -> None:
    with pytest.raises(SystemExit):
        cfg(["p", "/d", "--log-level", "LOUD"])
