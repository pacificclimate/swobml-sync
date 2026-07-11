"""Logging shared by the CLI's stderr stream and each run's persistent log file.

Every run writes a log file under the partner's ``logs`` directory keyed by the
run's ``runts`` — the same correlation key its manifest and stdout summary carry
— so a red run traced from its summary leads straight to its exact log. That
file and the stderr stream carry the *same* records at the same ``--log-level``,
so this one module owns the format string and the file-handler shape they share.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"


@contextmanager
def run_log_file(logger: logging.Logger, path: Path, level: str) -> Iterator[None]:
    """Route ``logger``'s records to ``path`` for the duration of the run.

    The file handler is created eagerly, so the log exists even for a run that
    emits nothing, and is removed and closed on exit so repeated runs in one
    process never leak handlers or open files. ``level`` is applied to both the
    logger and the handler, so the file honours ``--log-level`` on its own,
    independent of how the caller configured the root stderr stream.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler.setLevel(level)
    previous = logger.level
    logger.setLevel(level)
    logger.addHandler(handler)
    try:
        yield
    finally:
        logger.removeHandler(handler)
        handler.close()
        logger.setLevel(previous)
