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
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from swobml_sync.client import NotFound, RequestsClient

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
