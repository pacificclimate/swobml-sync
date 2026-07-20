"""Resolve the program's configuration from command-line args and environment.

Every flag has a ``SWOBML_*`` environment-variable fallback; an explicit
command-line argument always wins over the environment, which in turn wins over
the hard-coded default. The single seam for this is :func:`resolve_config`.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence

DEFAULT_DAYS_BACK = 2
DEFAULT_WORKERS = 8
DEFAULT_LOG_LEVEL = "INFO"

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

_DATE_FORMAT = "%Y%m%d"


@dataclass(frozen=True)
class Config:
    """Fully-resolved run configuration."""

    partner: str
    directory: Path
    days_back: int
    days: tuple[str, ...]
    as_of: str | None
    retention_days: int | None
    workers: int
    manifest: Path | None
    log_level: str


def _is_valid_day(value: str) -> bool:
    """Whether ``value`` is a real ``YYYYMMDD`` day."""
    try:
        datetime.strptime(value, _DATE_FORMAT)
    except ValueError:
        return False
    return True


def _valid_day(value: str) -> str:
    """argparse ``type`` for a ``YYYYMMDD`` day; returns it unchanged.

    Shared by ``--date`` and ``--as-of``; argparse prefixes the offending flag
    name, so the message stays flag-agnostic.
    """
    if not _is_valid_day(value):
        raise argparse.ArgumentTypeError(f"invalid day {value!r}, expected YYYYMMDD")
    return value


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    All defaults are ``None`` so that "absent from the command line" is
    distinguishable from an explicit value, letting :func:`resolve_config` apply
    the environment fallback and then the real default.
    """
    parser = argparse.ArgumentParser(
        prog="swobml-sync",
        description=(
            "Sync one swob-ml partner's hourly observation files from the ECCC "
            "HPFX server to a local directory tree."
        ),
    )
    parser.add_argument(
        "partner",
        nargs="?",
        default=None,
        help="partner slug to sync, e.g. nb-firewx (env: SWOBML_PARTNER)",
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=None,
        metavar="dir",
        help="output directory (env: SWOBML_DIR)",
    )
    parser.add_argument(
        "--days-back",
        type=int,
        default=None,
        metavar="N",
        help=f"rolling lookback window in days, UTC (default {DEFAULT_DAYS_BACK}; env: SWOBML_DAYS_BACK)",
    )
    parser.add_argument(
        "--date",
        action="append",
        type=_valid_day,
        default=None,
        metavar="YYYYMMDD",
        help="sync exactly these days, replacing the window; repeatable (env: SWOBML_DATE)",
    )
    parser.add_argument(
        "--as-of",
        type=_valid_day,
        default=None,
        metavar="YYYYMMDD",
        help="anchor the rolling window's newest day here instead of today (env: SWOBML_AS_OF)",
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=None,
        metavar="N",
        help="purge state/manifests/logs older than N days; overrides the "
        "server-discovered horizon and its 30-day floor (env: SWOBML_RETENTION_DAYS)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        metavar="N",
        help=f"download/discovery thread-pool size (default {DEFAULT_WORKERS}; env: SWOBML_WORKERS)",
    )
    parser.add_argument(
        "--manifest",
        default=None,
        metavar="PATH",
        help="override the default manifest location (env: SWOBML_MANIFEST)",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        metavar="LEVEL",
        help=f"logging level (default {DEFAULT_LOG_LEVEL}; env: SWOBML_LOG_LEVEL)",
    )
    return parser


def _resolve_int(
    parser: argparse.ArgumentParser,
    cli_value: int | None,
    env: Mapping[str, str],
    env_key: str,
    default: int,
    flag: str,
    *,
    minimum: int,
) -> int:
    """CLI value, else validated env value, else default; enforce a minimum."""
    if cli_value is not None:
        value = cli_value
    elif env.get(env_key):
        try:
            value = int(env[env_key])
        except ValueError:
            parser.error(f"{env_key} must be an integer (got {env[env_key]!r})")
    else:
        value = default
    if value < minimum:
        parser.error(f"{flag} must be >= {minimum} (got {value})")
    return value


def _resolve_opt_int(
    parser: argparse.ArgumentParser,
    cli_value: int | None,
    env: Mapping[str, str],
    env_key: str,
    flag: str,
    *,
    minimum: int,
) -> int | None:
    """CLI value, else validated env value, else ``None`` (absent, not defaulted).

    ``None`` marks "not set" so the caller can fall back to a discovered value
    rather than a fixed default; a value that *is* supplied still enforces the
    minimum.
    """
    if cli_value is not None:
        value = cli_value
    elif env.get(env_key):
        try:
            value = int(env[env_key])
        except ValueError:
            parser.error(f"{env_key} must be an integer (got {env[env_key]!r})")
    else:
        return None
    if value < minimum:
        parser.error(f"{flag} must be >= {minimum} (got {value})")
    return value


def _resolve_str(
    cli_value: str | None, env: Mapping[str, str], env_key: str
) -> str | None:
    """CLI value, else the environment value; ``None`` if neither is set."""
    return cli_value if cli_value is not None else env.get(env_key)


def _resolve_day(
    parser: argparse.ArgumentParser,
    cli_value: str | None,
    env: Mapping[str, str],
    env_key: str,
) -> str | None:
    """CLI day, else the env day, format-validated; ``None`` if neither is set.

    The CLI value is already validated by argparse's ``_valid_day`` type, so this
    only needs to re-check a value that arrived via the environment.
    """
    value = _resolve_str(cli_value, env, env_key)
    if value is not None and not _is_valid_day(value):
        parser.error(f"{env_key} must be a YYYYMMDD day (got {value!r})")
    return value


def _resolve_days(
    parser: argparse.ArgumentParser,
    cli_days: list[str] | None,
    env: Mapping[str, str],
) -> tuple[str, ...]:
    """CLI days win; otherwise parse SWOBML_DATE as a comma/space separated list."""
    if cli_days is not None:
        return tuple(cli_days)
    raw = env.get("SWOBML_DATE")
    if not raw:
        return ()
    days: list[str] = []
    for token in raw.replace(",", " ").split():
        if not _is_valid_day(token):
            parser.error(
                f"SWOBML_DATE contains an invalid day {token!r} (expected YYYYMMDD)"
            )
        days.append(token)
    return tuple(days)


def resolve_config(
    argv: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> Config:
    """Resolve a :class:`Config` from ``argv`` and ``env``.

    Precedence for every field is: command-line argument > environment variable
    > default. Any invalid input exits non-zero via ``argparse`` with a readable
    message.
    """
    env = os.environ if env is None else env
    parser = build_parser()
    ns = parser.parse_args(argv)

    partner = _resolve_str(ns.partner, env, "SWOBML_PARTNER")
    if not partner:
        parser.error("partner is required (positional argument or SWOBML_PARTNER)")

    directory_raw = _resolve_str(ns.directory, env, "SWOBML_DIR")
    if not directory_raw:
        parser.error("dir is required (positional argument or SWOBML_DIR)")

    days_back = _resolve_int(
        parser,
        ns.days_back,
        env,
        "SWOBML_DAYS_BACK",
        DEFAULT_DAYS_BACK,
        "--days-back",
        minimum=0,
    )
    # Absent (None) means "discover the horizon from the server, floored at 30";
    # only an explicit value overrides that (ticket 11 / ADR 0004).
    retention_days = _resolve_opt_int(
        parser,
        ns.retention_days,
        env,
        "SWOBML_RETENTION_DAYS",
        "--retention-days",
        minimum=1,
    )
    workers = _resolve_int(
        parser,
        ns.workers,
        env,
        "SWOBML_WORKERS",
        DEFAULT_WORKERS,
        "--workers",
        minimum=1,
    )

    days = _resolve_days(parser, ns.date, env)

    as_of = _resolve_day(parser, ns.as_of, env, "SWOBML_AS_OF")

    manifest_raw = _resolve_str(ns.manifest, env, "SWOBML_MANIFEST")
    manifest = Path(manifest_raw) if manifest_raw else None

    log_level_raw = _resolve_str(ns.log_level, env, "SWOBML_LOG_LEVEL")
    log_level = (log_level_raw or DEFAULT_LOG_LEVEL).upper()
    if log_level not in LOG_LEVELS:
        parser.error(
            f"--log-level must be one of {', '.join(LOG_LEVELS)} (got {log_level!r})"
        )

    return Config(
        partner=partner,
        directory=Path(directory_raw),
        days_back=days_back,
        days=days,
        as_of=as_of,
        retention_days=retention_days,
        workers=workers,
        manifest=manifest,
        log_level=log_level,
    )
