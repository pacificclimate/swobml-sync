"""Tests for the HTTP client: retry/backoff, 404-as-empty, and downloads.

Retry lives in urllib3 below the requests Session, so these tests drive a real
loopback HTTP server (no external network) to prove the configured policy end to
end: transient 503s are retried until success, a 404 surfaces as
:class:`NotFound`, and a persistently-failing endpoint gives up after the bounded
attempts rather than looping forever.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from swobml_sync.client import CountingClient, NotFound, RequestsClient

# A backoff of zero keeps retry tests instant; production backoff is exercised by
# the policy's real default, not by these behavioural tests.
NO_BACKOFF = 0.0


class _PlannedServer(HTTPServer):
    """An HTTP server that returns a scripted sequence of statuses per path.

    ``plan`` maps a path to the status codes to return on successive hits; the
    last entry repeats once exhausted. A ``200`` responds with the path as its
    body so callers can assert they reached the real resource.
    """

    def __init__(self, plan: dict[str, list[int]]) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.plan = plan
        self.hits: dict[str, int] = {}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # silence test-server logging
        pass

    def do_GET(self) -> None:
        server: _PlannedServer = self.server  # type: ignore[assignment]
        n = server.hits.get(self.path, 0)
        server.hits[self.path] = n + 1
        statuses = server.plan.get(self.path, [200])
        status = statuses[min(n, len(statuses) - 1)]
        body = self.path.encode() if status == 200 else b"transient"
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@contextlib.contextmanager
def _serving(plan: dict[str, list[int]]) -> Iterator[str]:
    server = _PlannedServer(plan)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[0], server.server_address[1]
        yield f"http://{host!s}:{port}"
    finally:
        server.shutdown()
        server.server_close()


def test_get_text_retries_transient_then_succeeds() -> None:
    with _serving({"/idx": [503, 503, 200]}) as base:
        client = RequestsClient(retries=3, backoff=NO_BACKOFF)
        assert client.get_text(f"{base}/idx") == "/idx"


def test_get_text_404_raises_not_found() -> None:
    with _serving({"/missing/": [404]}) as base:
        client = RequestsClient(retries=3, backoff=NO_BACKOFF)
        with pytest.raises(NotFound):
            client.get_text(f"{base}/missing/")


def test_get_text_gives_up_after_persistent_transient() -> None:
    with _serving({"/down": [503]}) as base:
        client = RequestsClient(retries=2, backoff=NO_BACKOFF)
        with pytest.raises(Exception) as exc:  # noqa: PT011 - any non-NotFound failure
            client.get_text(f"{base}/down")
        assert not isinstance(exc.value, NotFound)


def test_download_retries_transient_then_writes(tmp_path: Path) -> None:
    with _serving({"/f.xml": [503, 200]}) as base:
        client = RequestsClient(retries=3, backoff=NO_BACKOFF)
        dest = tmp_path / "f.xml"
        client.download(f"{base}/f.xml", dest)
        assert dest.read_bytes() == b"/f.xml"


def test_download_failure_after_retries_leaves_no_file(tmp_path: Path) -> None:
    with _serving({"/f.xml": [503]}) as base:
        client = RequestsClient(retries=2, backoff=NO_BACKOFF)
        dest = tmp_path / "f.xml"
        with pytest.raises(
            Exception
        ):  # noqa: PT011 - transient give-up surfaces as an error
            client.download(f"{base}/f.xml", dest)
        assert not dest.exists()


# --- CountingClient (ticket 12) ----------------------------------------------


class _RecordingClient:
    """A minimal inner client CountingClient can wrap; optionally always fails."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.get_text_calls = 0
        self.download_calls = 0

    def get_text(self, url: str) -> str:
        self.get_text_calls += 1
        if self.fail:
            raise RuntimeError("boom")
        return "<pre></pre>"

    def download(self, url: str, dest: Path) -> None:
        self.download_calls += 1
        if self.fail:
            raise RuntimeError("boom")


def test_counting_client_forwards_and_tallies_by_method() -> None:
    inner = _RecordingClient()
    client = CountingClient(inner)

    assert client.get_text("u1") == "<pre></pre>"
    client.get_text("u2")
    client.download("f1", Path("d1"))

    # get_text is a listing_request, download is a download; the inner client is
    # still called through (forwarding), each exactly once.
    assert (client.listing_requests, client.downloads) == (2, 1)
    assert (inner.get_text_calls, inner.download_calls) == (2, 1)


def test_counting_client_counts_notfound_and_failures() -> None:
    # Every logical call counts regardless of outcome: a request was still issued.
    client = CountingClient(_RecordingClient(fail=True))
    for _ in range(3):
        with pytest.raises(RuntimeError):
            client.get_text("u")
    with pytest.raises(RuntimeError):
        client.download("f", Path("d"))

    not_found = CountingClient(_NotFoundClient())
    with pytest.raises(NotFound):
        not_found.get_text("u")

    assert (client.listing_requests, client.downloads) == (3, 1)
    assert (not_found.listing_requests, not_found.downloads) == (1, 0)


class _NotFoundClient:
    def get_text(self, url: str) -> str:
        raise NotFound(url)

    def download(self, url: str, dest: Path) -> None:  # pragma: no cover - unused
        raise AssertionError("not called")


def test_counting_client_is_thread_safe_under_concurrency() -> None:
    # The sync phases fan get_text/download out across a bounded pool, so the
    # increments must be guarded: concurrent calls must not lose a count.
    client = CountingClient(_RecordingClient())
    calls = 500

    def hit(i: int) -> None:
        if i % 2 == 0:
            client.get_text("u")
        else:
            client.download("f", Path("d"))

    with ThreadPoolExecutor(max_workers=16) as pool:
        for future in [pool.submit(hit, i) for i in range(calls)]:
            future.result()

    assert client.listing_requests + client.downloads == calls
    assert client.listing_requests == calls // 2
    assert client.downloads == calls // 2
