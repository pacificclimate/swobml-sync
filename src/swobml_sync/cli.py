"""Command-line entry point for swobml-sync.

Resolves configuration, configures logging to stderr, runs the sync, and prints
a one-line JSON summary of the run to stdout for the calling task runner.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Sequence

from swobml_sync.availability import DiscoveryError, GateError
from swobml_sync.client import HttpClient, RequestsClient
from swobml_sync.config import resolve_config
from swobml_sync.logsetup import LOG_FORMAT
from swobml_sync.sync import run, run_record

# Exit code for a pre-flight abort (availability discovery or the input gate),
# kept distinct from 1 (a run that did work but had per-file failures to retry).
EXIT_PREFLIGHT = 2


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
    try:
        result = run(
            config,
            client if client is not None else RequestsClient(pool_size=config.workers),
        )
    except (DiscoveryError, GateError) as exc:
        # A Tier-1 discovery failure or an out-of-window explicit day: abort before
        # any sync work, non-zero, with the reason (ticket 11 / ADR 0004).
        logging.getLogger("swobml_sync").error("aborting: %s", exc)
        return EXIT_PREFLIGHT
    # The stdout summary is the shared run record plus the run's manifest path, so
    # it stays a superset of what the persisted stats file holds (ticket 12).
    json.dump({**run_record(result), "manifest": result.manifest}, sys.stdout)
    sys.stdout.write("\n")
    # Successes are already persisted by run() (state + manifest). Exit non-zero
    # when anything failed permanently so the task runner (kestra) surfaces it
    # and the failed files are retried on the next run; zero when nothing failed,
    # including a run with nothing to do.
    return 1 if result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
