"""End-to-end sync of one day against fixture indexes and a mocked HTTP layer.

Exercises the whole pipeline — parse -> delta -> state-merge -> manifest — with
no network: a fake :class:`HttpClient` serves saved directory-index HTML and
canned file bodies keyed by the exact URLs :mod:`swobml_sync.layout` builds.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from swobml_sync import layout, state
from swobml_sync.atomicio import write_atomic
from swobml_sync.config import resolve_config
from swobml_sync.sync import run

FIXTURES = Path(__file__).parent / "fixtures"
PARTNER = "bc-RioTinto"
DAY = "20260710"
FILES = {
    "kenn": [
        "2026-07-10-0000-riotinto-kenn-kenn-AUTO-swob.xml",
        "2026-07-10-0100-riotinto-kenn-kenn-AUTO-swob.xml",
    ],
    "eutk": ["2026-07-10-0000-riotinto-eutk-eutk-AUTO-swob.xml"],
}


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeClient:
    """Serves index pages and file bodies keyed by URL; records what it fetched.

    ``text_errors`` maps a URL to an exception ``get_text`` raises instead of
    serving it, standing in for a ``404`` (:class:`NotFound`) or a listing that
    kept failing after the client's own retries were exhausted.
    """

    def __init__(
        self,
        pages: dict[str, str],
        bodies: dict[str, bytes],
        *,
        text_errors: dict[str, Exception] | None = None,
    ) -> None:
        self._pages = pages
        self._bodies = bodies
        self._text_errors = text_errors or {}
        self.downloaded: list[str] = []

    def get_text(self, url: str) -> str:
        if url in self._text_errors:
            raise self._text_errors[url]
        return self._pages[url]

    def download(self, url: str, dest: Path) -> None:
        write_atomic(dest, self._bodies[url])
        self.downloaded.append(url)


def _pages(day_fixture: str = "sync_day.html") -> dict[str, str]:
    return {
        layout.day_url(PARTNER, DAY): _read(day_fixture),
        layout.station_url(PARTNER, DAY, "kenn"): _read("sync_kenn.html"),
        layout.station_url(PARTNER, DAY, "eutk"): _read("sync_eutk.html"),
    }


def _bodies() -> dict[str, bytes]:
    bodies: dict[str, bytes] = {}
    for station, names in FILES.items():
        for name in names:
            url = layout.file_url(PARTNER, DAY, station, name)
            bodies[url] = f"<swob>{name}</swob>".encode()
    return bodies


def _config(directory: Path):  # type: ignore[no-untyped-def]
    return resolve_config([PARTNER, str(directory), "--date", DAY], env={})


def _pages_for_days(days: list[str]) -> dict[str, str]:
    """The fixture indexes served under each day's URLs, for a rolling-window run."""
    pages: dict[str, str] = {}
    for day in days:
        pages[layout.day_url(PARTNER, day)] = _read("sync_day.html")
        pages[layout.station_url(PARTNER, day, "kenn")] = _read("sync_kenn.html")
        pages[layout.station_url(PARTNER, day, "eutk")] = _read("sync_eutk.html")
    return pages


def _bodies_for_days(days: list[str]) -> dict[str, bytes]:
    bodies: dict[str, bytes] = {}
    for day in days:
        for station, names in FILES.items():
            for name in names:
                bodies[layout.file_url(PARTNER, day, station, name)] = f"<swob>{name}</swob>".encode()
    return bodies


def test_first_run_downloads_all_files(tmp_path: Path) -> None:
    client = FakeClient(_pages(), _bodies())
    result = run(_config(tmp_path), client)

    assert (result.added, result.changed, result.failed) == (3, 0, 0)
    assert result.days == [DAY]
    # Files land in the cache tree with the served bytes.
    kenn0 = layout.local_file_path(tmp_path, PARTNER, DAY, "kenn", FILES["kenn"][0])
    assert kenn0.read_text() == f"<swob>{FILES['kenn'][0]}</swob>"


def test_state_records_only_downloaded_files(tmp_path: Path) -> None:
    run(_config(tmp_path), FakeClient(_pages(), _bodies()))
    saved = state.load(layout.state_path(tmp_path, PARTNER))
    assert set(saved[DAY]["kenn"]) == set(FILES["kenn"])
    assert saved[DAY]["kenn"][FILES["kenn"][0]] == {"mtime": "2026-07-10 01:50", "size": "3.3K"}


def test_manifest_lists_every_delta(tmp_path: Path) -> None:
    result = run(_config(tmp_path), FakeClient(_pages(), _bodies()))
    lines = Path(result.manifest).read_text().splitlines()
    assert len(lines) == 3
    rec = json.loads(lines[0])
    assert rec["action"] == "added"
    assert rec["day"] == DAY
    assert rec["path"].startswith(f"{PARTNER}/cache/{DAY}/")


def test_second_unchanged_run_is_empty(tmp_path: Path) -> None:
    run(_config(tmp_path), FakeClient(_pages(), _bodies()))
    client2 = FakeClient(_pages(), _bodies())
    result = run(_config(tmp_path), client2)
    assert (result.added, result.changed, result.failed) == (0, 0, 0)
    assert client2.downloaded == []
    assert Path(result.manifest).read_text() == ""


def test_changed_upstream_file_is_redownloaded(tmp_path: Path) -> None:
    run(_config(tmp_path), FakeClient(_pages(), _bodies()))
    # kenn's second file gets a newer last-modified upstream.
    changed_pages = _pages("sync_day.html")
    changed_pages[layout.station_url(PARTNER, DAY, "kenn")] = _read("sync_kenn.html").replace(
        "2026-07-10 02:49", "2026-07-10 09:15"
    )
    result = run(_config(tmp_path), FakeClient(changed_pages, _bodies()))
    assert (result.added, result.changed, result.failed) == (0, 1, 0)
    rec = json.loads(Path(result.manifest).read_text().splitlines()[0])
    assert rec["action"] == "changed"


def test_failed_download_is_not_recorded(tmp_path: Path) -> None:
    bodies = _bodies()
    # Drop one body so its download raises KeyError inside the fake client.
    missing_url = layout.file_url(PARTNER, DAY, "eutk", FILES["eutk"][0])
    del bodies[missing_url]
    result = run(_config(tmp_path), FakeClient(_pages(), bodies))

    assert result.failed == 1
    assert result.added == 2
    saved = state.load(layout.state_path(tmp_path, PARTNER))
    assert "eutk" not in saved.get(DAY, {})
    # The failed file is left out of the manifest too, not just sync state.
    manifest_stations = {
        json.loads(line)["station"] for line in Path(result.manifest).read_text().splitlines()
    }
    assert "eutk" not in manifest_stations
    # A re-run retries the previously-failed file.
    retry = run(_config(tmp_path), FakeClient(_pages(), _bodies()))
    assert retry.added == 1


def test_no_partial_files_left_behind(tmp_path: Path) -> None:
    run(_config(tmp_path), FakeClient(_pages(), _bodies()))
    leftovers = list(tmp_path.rglob("*.tmp"))
    assert leftovers == []


def test_empty_day_still_writes_empty_manifest(tmp_path: Path) -> None:
    empty_day = (
        "<html><body><h1>Index of /x</h1><pre>"
        '<img src="/icons/back.gif" alt="[PARENTDIR]"> '
        '<a href="/parent/">Parent Directory</a>   -\n<hr></pre></body></html>'
    )
    pages = {layout.day_url(PARTNER, DAY): empty_day}
    result = run(_config(tmp_path), FakeClient(pages, {}))
    assert (result.added, result.changed, result.failed) == (0, 0, 0)
    assert Path(result.manifest).exists()
    assert Path(result.manifest).read_text() == ""


@pytest.mark.parametrize("station", list(FILES))
def test_files_grouped_by_station_directory(tmp_path: Path, station: str) -> None:
    run(_config(tmp_path), FakeClient(_pages(), _bodies()))
    for name in FILES[station]:
        assert layout.local_file_path(tmp_path, PARTNER, DAY, station, name).exists()


def test_station_404_is_treated_as_empty(tmp_path: Path) -> None:
    from swobml_sync.client import NotFound

    # eutk's directory 404s; it contributes nothing and is not a failure, while
    # kenn syncs normally.
    client = FakeClient(
        _pages(),
        _bodies(),
        text_errors={layout.station_url(PARTNER, DAY, "eutk"): NotFound("gone")},
    )
    result = run(_config(tmp_path), client)

    assert (result.added, result.changed, result.failed) == (2, 0, 0)
    saved = state.load(layout.state_path(tmp_path, PARTNER))
    assert set(saved[DAY]["kenn"]) == set(FILES["kenn"])
    assert "eutk" not in saved.get(DAY, {})


def test_day_404_is_treated_as_empty(tmp_path: Path) -> None:
    from swobml_sync.client import NotFound

    client = FakeClient(
        {}, {}, text_errors={layout.day_url(PARTNER, DAY): NotFound("gone")}
    )
    result = run(_config(tmp_path), client)

    assert (result.added, result.changed, result.failed) == (0, 0, 0)
    assert Path(result.manifest).read_text() == ""


def test_permanent_listing_failure_is_counted_and_run_continues(tmp_path: Path) -> None:
    # eutk's listing keeps failing (a non-404 error surfaced after retries): it
    # counts as a failure so the run exits non-zero and retries next time, but
    # kenn's successes are still discovered and persisted.
    client = FakeClient(
        _pages(),
        _bodies(),
        text_errors={layout.station_url(PARTNER, DAY, "eutk"): RuntimeError("503 exhausted")},
    )
    result = run(_config(tmp_path), client)

    assert result.failed == 1
    assert result.added == 2
    saved = state.load(layout.state_path(tmp_path, PARTNER))
    assert set(saved[DAY]["kenn"]) == set(FILES["kenn"])
    assert "eutk" not in saved.get(DAY, {})


NOW = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)


def test_no_date_processes_rolling_window(tmp_path: Path) -> None:
    days = ["20260710", "20260709"]
    config = resolve_config([PARTNER, str(tmp_path), "--days-back", "1"], env={})
    client = FakeClient(_pages_for_days(days), _bodies_for_days(days))

    result = run(config, client, now=NOW)

    # Both days processed, newest first; each day's three files added.
    assert result.days == days
    assert (result.added, result.changed, result.failed) == (6, 0, 0)
    saved = state.load(layout.state_path(tmp_path, PARTNER))
    assert set(saved) == set(days)


def test_date_overrides_days_back(tmp_path: Path) -> None:
    # A generous --days-back is ignored entirely when --date is given.
    config = resolve_config(
        [PARTNER, str(tmp_path), "--date", DAY, "--days-back", "5"], env={}
    )
    result = run(config, FakeClient(_pages(), _bodies()), now=NOW)
    assert result.days == [DAY]


def test_untouched_days_are_not_clobbered(tmp_path: Path) -> None:
    # A day recorded by an earlier backfill run, outside this run's window.
    old_day = "20260101"
    seeded = {old_day: {"anfi": {"old.xml": {"mtime": "2026-01-01 00:00", "size": "1K"}}}}
    state.save(layout.state_path(tmp_path, PARTNER), seeded)

    run(_config(tmp_path), FakeClient(_pages(), _bodies()), now=NOW)

    saved = state.load(layout.state_path(tmp_path, PARTNER))
    assert saved[old_day] == seeded[old_day]
    assert DAY in saved
