"""The HTTP layer: fetch directory indexes and download SWOB files.

This is the one seam the tests replace with a fixture-backed fake, so the
discovery -> delta -> state -> manifest pipeline runs without touching the
network. :class:`HttpClient` is that seam; :class:`RequestsClient` is the real
implementation over a pooled ``requests`` session.

Transient upstream problems — connection errors, ``429``, and ``5xx`` — are
retried with backoff by urllib3's :class:`Retry` mounted on the session (see
ADR 0003), a bounded number of times before the call finally raises. A ``404``
on a directory index is *not* an error: it means the day or station simply does
not exist upstream, so :meth:`RequestsClient.get_text` raises :class:`NotFound`
for the caller to treat as an empty listing rather than a failure.

Downloads land through :func:`swobml_sync.atomicio.write_atomic` so an
interrupted run never leaves a truncated SWOB file behind.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from swobml_sync.atomicio import write_atomic

# The transient HTTP statuses worth retrying: rate limiting and the gateway/
# server-side errors that typically clear on a second attempt.
RETRYABLE_STATUSES = (429, 500, 502, 503, 504)
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF = 0.5


class NotFound(Exception):
    """A ``404`` on a directory index: the day or station does not exist upstream.

    Not a failure — the caller treats it as a legitimately empty listing.
    """


class HttpClient(Protocol):
    """Fetch a directory index as text, or download a file to a local path."""

    def get_text(self, url: str) -> str: ...

    def download(self, url: str, dest: Path) -> None: ...


def _retrying_session(retries: int, backoff: float, pool_size: int) -> requests.Session:
    """A pooled session whose adapter retries transient failures with backoff.

    ``pool_size`` sizes the adapter's connection pool to the worker count so a
    concurrent run reuses one connection per worker instead of opening (and
    discarding) fresh sockets past the default pool ceiling.
    """
    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        status=retries,
        backoff_factor=backoff,
        status_forcelist=RETRYABLE_STATUSES,
        allowed_methods=frozenset({"GET"}),
        raise_on_status=True,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(
        max_retries=retry, pool_connections=pool_size, pool_maxsize=pool_size
    )
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


class RequestsClient:
    """A :class:`HttpClient` over a pooled ``requests`` session with retry/backoff."""

    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: float = 30.0,
        *,
        retries: int = DEFAULT_RETRIES,
        backoff: float = DEFAULT_BACKOFF,
        pool_size: int = 1,
    ) -> None:
        self._session = (
            session
            if session is not None
            else _retrying_session(retries, backoff, pool_size)
        )
        self._timeout = timeout

    def get_text(self, url: str) -> str:
        """Fetch a directory index; a ``404`` raises :class:`NotFound`.

        Transient failures are already retried inside the session; if they never
        clear, the underlying ``requests`` error propagates so the caller can
        treat the listing as a (permanent) failure.
        """
        response = self._session.get(url, timeout=self._timeout)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                raise NotFound(url) from exc
            raise
        return response.text

    def download(self, url: str, dest: Path) -> None:
        response = self._session.get(url, timeout=self._timeout)
        response.raise_for_status()
        write_atomic(dest, response.content)
