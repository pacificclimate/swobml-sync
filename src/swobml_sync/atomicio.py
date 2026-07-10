"""Atomic file writes.

Both the sync state and every downloaded SWOB file must land whole-or-not-at-all
so a killed run never leaves a torn file behind. The shape is the same for both:
write a temp sibling, then ``os.replace`` it into place (atomic on the same
filesystem). This one helper owns that shape (see ADR 0001).
"""

from __future__ import annotations

import os
from pathlib import Path


def write_atomic(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` via a temp sibling and ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
