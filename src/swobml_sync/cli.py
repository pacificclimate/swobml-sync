"""Command-line entry point for swobml-sync.

Ticket 01 establishes the CLI surface only: it resolves and validates the full
configuration. Actually syncing files arrives in later tickets.
"""

from __future__ import annotations

import sys
from typing import Sequence

from swobml_sync.config import resolve_config


def main(argv: Sequence[str] | None = None) -> int:
    config = resolve_config(argv)
    print(
        f"swobml-sync: resolved configuration for partner {config.partner!r} "
        f"-> {config.directory}",
        file=sys.stderr,
    )
    print(
        "swobml-sync: no sync implemented yet (scaffold only — see .scratch tickets)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
