"""Command-line entry point for swobml-sync.

Resolves configuration, configures logging to stderr, runs the sync, and prints
a one-line JSON summary of the run to stdout for the calling task runner.
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import asdict
from typing import Sequence

from swobml_sync.client import HttpClient, RequestsClient
from swobml_sync.config import resolve_config
from swobml_sync.logsetup import LOG_FORMAT
from swobml_sync.sync import run


def main(argv: Sequence[str] | None = None, client: HttpClient | None = None) -> int:
    """Resolve config, run the sync, print the JSON summary; ``client`` is a seam for tests."""
    config = resolve_config(argv)
    logging.basicConfig(
        level=config.log_level,
        stream=sys.stderr,
        format=LOG_FORMAT,
    )
    # Size the real client's connection pool to the worker count so concurrent
    # discovery and downloads reuse one connection per worker (see ticket 05).
    result = run(
        config,
        client if client is not None else RequestsClient(pool_size=config.workers),
    )
    json.dump(
        {
            "runts": result.runts,
            "manifest": result.manifest,
            "added": result.added,
            "changed": result.changed,
            "failed": result.failed,
            "days": result.days,
            "coverage": asdict(result.coverage),
        },
        sys.stdout,
    )
    sys.stdout.write("\n")
    # Successes are already persisted by run() (state + manifest). Exit non-zero
    # when anything failed permanently so the task runner (kestra) surfaces it
    # and the failed files are retried on the next run; zero when nothing failed,
    # including a run with nothing to do.
    return 1 if result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
