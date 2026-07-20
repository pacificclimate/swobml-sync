"""Concurrency guarantees for a run (ticket 05).

The end-to-end behaviour under concurrency — identical files, state, manifest,
and the retry / 404-as-empty / permanent-failure semantics — is already covered
by :mod:`test_sync`, whose fixtures run at the default eight workers. These tests
pin the concurrency-specific claims the other suite can't observe: that work
actually runs in parallel, that the pool is *bounded* by ``--workers``, that the
outputs are independent of the worker count, and that the real client shares one
pool-sized session.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from swobml_sync import layout, state
from swobml_sync.atomicio import write_atomic
from swobml_sync.client import RequestsClient
from swobml_sync.config import resolve_config
from swobml_sync.sync import run

PARTNER = "bc-RioTinto"
DAY = "20260710"


def _index(rows: list[tuple[str, bool]]) -> str:
    """A minimal Apache fancy-index page for ``(name, is_dir)`` rows."""
    lines = [
        '<img src="/icons/back.gif" alt="[PARENTDIR]"> '
        '<a href="/parent/">Parent Directory</a>   -'
    ]
    for name, is_dir in rows:
        href = f"{name}/" if is_dir else name
        size = "-" if is_dir else "3.3K"
        lines.append(f'<a href="{href}">{href}</a>   2026-07-10 01:50  {size}')
    body = "\n".join(lines)
    return f"<html><body><h1>Index</h1><pre>{body}<hr></pre></body></html>"


def _source(
    stations: list[str], files_per_station: int
) -> tuple[dict[str, str], dict[str, bytes]]:
    """Fixture pages and bodies for one day of ``stations`` each with N files."""
    pages = {layout.day_url(PARTNER, DAY): _index([(s, True) for s in stations])}
    bodies: dict[str, bytes] = {}
    for station in stations:
        names = [f"{DAY}-{station}-{h:02d}.xml" for h in range(files_per_station)]
        pages[layout.station_url(PARTNER, DAY, station)] = _index(
            [(n, False) for n in names]
        )
        for name in names:
            bodies[layout.file_url(PARTNER, DAY, station, name)] = (
                f"<swob>{name}</swob>".encode()
            )
    return pages, bodies


class _TrackingClient:
    """Serves a fixed source and records how many downloads overlap.

    Each download optionally waits on a shared :class:`~threading.Barrier` before
    returning, which lets a test prove downloads run in parallel (the barrier only
    releases once ``parties`` of them are in flight at once) while a counter proves
    the pool never runs more than ``--workers`` at a time.
    """

    def __init__(
        self,
        pages: dict[str, str],
        bodies: dict[str, bytes],
        *,
        barrier: threading.Barrier | None = None,
    ) -> None:
        self._pages = pages
        self._bodies = bodies
        self._barrier = barrier
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.downloaded: list[str] = []

    def get_text(self, url: str) -> str:
        if url == layout.root_url():
            # Make the requested day available so discovery + the gate pass.
            return _index([(DAY, True)])
        return self._pages[url]

    def download(self, url: str, dest: Path) -> None:
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self._barrier is not None:
                self._barrier.wait(timeout=5)
            write_atomic(dest, self._bodies[url])
        finally:
            with self._lock:
                self.active -= 1
        with self._lock:
            self.downloaded.append(url)


def _config(directory: Path, workers: int):  # type: ignore[no-untyped-def]
    return resolve_config(
        [PARTNER, str(directory), "--date", DAY, "--workers", str(workers)], env={}
    )


def test_downloads_run_concurrently(tmp_path: Path) -> None:
    # Three downloads must be in flight at once for the barrier to release; if the
    # run serialised them, the first would block forever and time out below.
    pages, bodies = _source(["a", "b", "c"], files_per_station=1)
    barrier = threading.Barrier(3)
    client = _TrackingClient(pages, bodies, barrier=barrier)

    run(_config(tmp_path, workers=8), client)

    assert client.max_active == 3
    assert len(client.downloaded) == 3


def test_pool_is_bounded_by_workers(tmp_path: Path) -> None:
    # Eight files but only two workers: the pool must never run more than two
    # downloads at once. A barrier sized to the worker count guarantees it does
    # reach the bound (paired downloads meet at it) rather than staying serial.
    pages, bodies = _source(["a", "b", "c", "d"], files_per_station=2)
    barrier = threading.Barrier(2)
    client = _TrackingClient(pages, bodies, barrier=barrier)

    run(_config(tmp_path, workers=2), client)

    assert client.max_active == 2
    assert len(client.downloaded) == 8


def test_output_is_independent_of_worker_count(tmp_path: Path) -> None:
    # The same source synced serially (one worker) and highly concurrent (eight)
    # must yield identical sync state and identical manifest lines.
    pages, bodies = _source(["a", "b", "c"], files_per_station=4)

    serial_dir = tmp_path / "serial"
    concurrent_dir = tmp_path / "concurrent"
    serial = run(_config(serial_dir, workers=1), _TrackingClient(pages, bodies))
    concurrent = run(_config(concurrent_dir, workers=8), _TrackingClient(pages, bodies))

    assert (serial.added, serial.changed, serial.failed) == (12, 0, 0)
    assert (concurrent.added, concurrent.changed, concurrent.failed) == (
        serial.added,
        serial.changed,
        serial.failed,
    )
    assert state.load(layout.state_path(serial_dir, PARTNER)) == state.load(
        layout.state_path(concurrent_dir, PARTNER)
    )
    assert (
        Path(serial.manifest).read_text().splitlines()
        == Path(concurrent.manifest).read_text().splitlines()
    )


@pytest.mark.parametrize("pool_size", [1, 4, 16])
def test_client_session_pool_sized_to_workers(pool_size: int) -> None:
    # One shared session, its https/http adapters sized to the worker count so a
    # concurrent run reuses a connection per worker instead of discarding sockets.
    client = RequestsClient(pool_size=pool_size)
    session = client._session

    https = session.get_adapter("https://example/")
    http = session.get_adapter("http://example/")
    assert https is client._session.get_adapter("https://other/")
    assert https._pool_maxsize == pool_size  # type: ignore[attr-defined]
    assert http._pool_maxsize == pool_size  # type: ignore[attr-defined]
