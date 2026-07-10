"""The HTTP layer: fetch directory indexes and download SWOB files.

This is the one seam the tests replace with a fixture-backed fake, so the
discovery -> delta -> state -> manifest pipeline runs without touching the
network. :class:`HttpClient` is that seam; :class:`RequestsClient` is the real
implementation over a pooled ``requests`` session (retry/backoff arrives in a
later ticket).

Downloads land through :func:`swobml_sync.atomicio.write_atomic` so an
interrupted run never leaves a truncated SWOB file behind.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import requests

from swobml_sync.atomicio import write_atomic


class HttpClient(Protocol):
    """Fetch a directory index as text, or download a file to a local path."""

    def get_text(self, url: str) -> str: ...

    def download(self, url: str, dest: Path) -> None: ...


class RequestsClient:
    """A :class:`HttpClient` over a pooled ``requests`` session."""

    def __init__(self, session: requests.Session | None = None, timeout: float = 30.0) -> None:
        self._session = session if session is not None else requests.Session()
        self._timeout = timeout

    def get_text(self, url: str) -> str:
        response = self._session.get(url, timeout=self._timeout)
        response.raise_for_status()
        return response.text

    def download(self, url: str, dest: Path) -> None:
        response = self._session.get(url, timeout=self._timeout)
        response.raise_for_status()
        write_atomic(dest, response.content)
