"""Parse an Apache directory index into listing entries.

The ECCC HPFX server publishes a standard Apache ``fancy index`` for every
directory: a ``<pre>`` block, one entry per line, where each entry is an icon,
an ``<a>`` link, and — in the text trailing the link — the last-modified stamp
and size (e.g. ``... 2026-07-10 01:50  3.3K``). Discovery of a day's stations
and a station's SWOB files reads those lines here; no filename parsing (day and
station come from the path, per CONTEXT.md).

Change detection compares the ``(last-modified, size)`` pair each line carries
against sync state (see ADR 0002), so both fields are kept verbatim as the
strings the server rendered rather than being reinterpreted — the size is the
human-readable form (``3.3K``), not a byte count.
"""

from __future__ import annotations

from dataclasses import dataclass

import lxml.html


@dataclass(frozen=True)
class Entry:
    """One row of a directory index: a subdirectory or a file.

    ``last_modified`` and ``size`` are the raw strings from the index (``size``
    is ``None`` for a directory). They are treated as opaque change-detection
    tokens, never parsed into numbers or timestamps.
    """

    name: str
    is_dir: bool
    last_modified: str | None
    size: str | None


def directories(entries: list[Entry]) -> list[str]:
    """Names of the directory entries, in listing order (e.g. the stations)."""
    return [e.name for e in entries if e.is_dir]


def files(entries: list[Entry]) -> list[Entry]:
    """The file entries, in listing order (e.g. a station's SWOB files)."""
    return [e for e in entries if not e.is_dir]


def parse_index(html: str) -> list[Entry]:
    """Parse Apache index ``html`` into entries, skipping navigation rows.

    Column-sort links (``?C=...``), the parent-directory link, and the icon
    column are ignored; every remaining anchor is one real entry, a directory
    when its href ends in ``/``.
    """
    doc = lxml.html.fromstring(html)
    entries: list[Entry] = []
    for anchor in doc.iter("a"):
        href = anchor.get("href")
        if href is None:
            continue
        if href.startswith("?") or href.startswith("/") or href.startswith(".."):
            # Sort links, absolute Parent Directory links, and "../" — not entries.
            continue
        is_dir = href.endswith("/")
        name = href[:-1] if is_dir else href
        last_modified, size = _row_metadata(anchor)
        entries.append(
            Entry(
                name=name,
                is_dir=is_dir,
                last_modified=last_modified,
                size=None if is_dir else size,
            )
        )
    return entries


def _row_metadata(anchor: lxml.html.HtmlElement) -> tuple[str | None, str | None]:
    """Read last-modified and size from the text trailing the anchor.

    The trailing text for a fancy-index line looks like
    ``   2026-07-10 01:50  3.3K`` (a directory shows ``-`` for size). Tokenising
    on whitespace, the final token is the size and the two before it are the
    date and time.
    """
    tokens = (anchor.tail or "").split()
    if len(tokens) < 3:
        return None, None
    last_modified = " ".join(tokens[-3:-1])
    size = tokens[-1]
    return last_modified, _blank_to_none(size)


def _blank_to_none(text: str) -> str | None:
    return None if text == "-" else text
