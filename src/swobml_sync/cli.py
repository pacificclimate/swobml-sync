"""Command-line entry point for swobml-sync.

Resolves configuration, configures logging to stderr, runs the sync, and prints
a one-line JSON summary of the run to stdout for the calling task runner.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Sequence

from swobml_sync.client import HttpClient, RequestsClient
from swobml_sync.config import resolve_config
from swobml_sync.sync import run


def main(argv: Sequence[str] | None = None, client: HttpClient | None = None) -> int:
    """Resolve config, run the sync, print the JSON summary; ``client`` is a seam for tests."""
    config = resolve_config(argv)
    logging.basicConfig(
        level=config.log_level,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    result = run(config, client if client is not None else RequestsClient())
    json.dump(
        {
            "manifest": result.manifest,
            "added": result.added,
            "changed": result.changed,
            "failed": result.failed,
            "days": result.days,
        },
        sys.stdout,
    )
    sys.stdout.write("\n")
    # Per-file failures are reported in the summary; how they map to an exit
    # code is defined in ticket 04 (retry and failure exit semantics).
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
