"""End-to-end sync of one day against fixture indexes and a mocked HTTP layer.

Exercises the whole pipeline — parse -> delta -> state-merge -> manifest — with
no network: a fake :class:`HttpClient` serves saved directory-index HTML and
canned file bodies keyed by the exact URLs :mod:`swobml_sync.layout` builds.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from swobml_sync import cli, layout, state
from swobml_sync.atomicio import write_atomic
from swobml_sync.availability import DiscoveryError, GateError
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


def root_index(days: list[str]) -> str:
    """An Apache root-index page listing ``days`` as ``YYYYMMDD/`` directories."""
    rows = "\n".join(
        f'<img src="/icons/folder.gif" alt="[DIR]"> '
        f'<a href="{day}/">{day}/</a>  2026-07-10 00:00  -'
        for day in days
    )
    return (
        "<html><body><h1>Index of /</h1><pre>"
        '<img src="/icons/back.gif" alt="[PARENTDIR]"> '
        '<a href="/parent/">Parent Directory</a>   -\n'
        f"{rows}\n<hr></pre></body></html>"
    )


def _day_span(start: str, end: str) -> list[str]:
    """Every ``YYYYMMDD`` day from ``start`` to ``end`` inclusive."""
    lo = datetime.strptime(start, "%Y%m%d").date()
    hi = datetime.strptime(end, "%Y%m%d").date()
    out: list[str] = []
    cur = lo
    while cur <= hi:
        out.append(cur.strftime("%Y%m%d"))
        cur += timedelta(days=1)
    return out


# The availability window the fake serves by default: earliest 20260501, latest
# 20260710 (the fixture day). Discovery reads this so runs don't need to stub the
# root index; tests exercising discovery/gate edges override it explicitly.
AVAILABLE_DAYS = _day_span("20260501", "20260710")


class FakeClient:
    """Serves index pages and file bodies keyed by URL; records what it fetched.

    ``text_errors`` maps a URL to an exception ``get_text`` raises instead of
    serving it, standing in for a ``404`` (:class:`NotFound`) or a listing that
    kept failing after the client's own retries were exhausted. The root index
    (availability discovery) is served from a default wide window unless a test
    supplies its own under ``layout.root_url()`` or errors it via ``text_errors``.
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
        if url == layout.root_url() and url not in self._pages:
            return root_index(AVAILABLE_DAYS)
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
                bodies[layout.file_url(PARTNER, day, station, name)] = (
                    f"<swob>{name}</swob>".encode()
                )
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
    assert saved[DAY]["kenn"][FILES["kenn"][0]] == {
        "mtime": "2026-07-10 01:50",
        "size": "3.3K",
    }


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
    changed_pages[layout.station_url(PARTNER, DAY, "kenn")] = _read(
        "sync_kenn.html"
    ).replace("2026-07-10 02:49", "2026-07-10 09:15")
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
        json.loads(line)["station"]
        for line in Path(result.manifest).read_text().splitlines()
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
        text_errors={
            layout.station_url(PARTNER, DAY, "eutk"): RuntimeError("503 exhausted")
        },
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


def test_as_of_anchors_window_on_a_historic_day(tmp_path: Path) -> None:
    # --as-of moves the newest day of the window; --days-back counts back from it,
    # so `now` (the 10th) is irrelevant to the data window.
    anchored = ["20260601", "20260531"]
    config = resolve_config(
        [PARTNER, str(tmp_path), "--as-of", "20260601", "--days-back", "1"], env={}
    )
    client = FakeClient(_pages_for_days(anchored), _bodies_for_days(anchored))

    result = run(config, client, now=NOW)

    assert result.days == anchored
    assert (result.added, result.changed, result.failed) == (6, 0, 0)


def test_as_of_from_env_anchors_window(tmp_path: Path) -> None:
    anchored = ["20260601"]
    config = resolve_config(
        [PARTNER, str(tmp_path), "--days-back", "0"], env={"SWOBML_AS_OF": "20260601"}
    )
    client = FakeClient(_pages_for_days(anchored), _bodies_for_days(anchored))

    result = run(config, client, now=NOW)

    assert result.days == anchored


def test_date_and_as_of_ignores_as_of_and_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # --date replaces the window outright, so --as-of is dropped — but loudly,
    # at WARNING, because it is a specific, intentful request.
    config = resolve_config(
        [PARTNER, str(tmp_path), "--date", DAY, "--as-of", "20260601"], env={}
    )
    with caplog.at_level("WARNING", logger="swobml_sync"):
        result = run(config, FakeClient(_pages(), _bodies()), now=NOW)

    assert result.days == [DAY]
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("as-of" in r.getMessage().lower() for r in warnings)


def test_date_overrides_days_back(tmp_path: Path) -> None:
    # A generous --days-back is ignored entirely when --date is given.
    config = resolve_config(
        [PARTNER, str(tmp_path), "--date", DAY, "--days-back", "5"], env={}
    )
    result = run(config, FakeClient(_pages(), _bodies()), now=NOW)
    assert result.days == [DAY]


def test_run_writes_log_file_sharing_manifest_key(tmp_path: Path) -> None:
    result = run(_config(tmp_path), FakeClient(_pages(), _bodies()), now=NOW)

    log_file = layout.log_path(tmp_path, PARTNER, result.runts)
    # The log lives under the partner's logs dir, keyed by the run's runts, and
    # shares that one correlation key with the run's manifest.
    assert log_file.exists()
    assert log_file.stem == Path(result.manifest).stem == result.runts
    # At the default INFO level the run's records land in the file.
    assert "complete" in log_file.read_text()


def test_log_file_honours_log_level(tmp_path: Path) -> None:
    # At WARNING a clean run emits no records, so the file exists but is empty —
    # the same level that gates the stderr stream gates the file.
    config = resolve_config(
        [PARTNER, str(tmp_path), "--date", DAY, "--log-level", "WARNING"], env={}
    )
    result = run(config, FakeClient(_pages(), _bodies()), now=NOW)

    log_file = layout.log_path(tmp_path, PARTNER, result.runts)
    assert log_file.exists()
    assert log_file.read_text() == ""


def test_untouched_days_are_not_clobbered(tmp_path: Path) -> None:
    # A day recorded by an earlier backfill run, outside this run's window but
    # still within the retention horizon so end-of-run purge leaves it alone.
    old_day = "20260601"
    seeded = {
        old_day: {"anfi": {"old.xml": {"mtime": "2026-06-01 00:00", "size": "1K"}}}
    }
    state.save(layout.state_path(tmp_path, PARTNER), seeded)

    run(_config(tmp_path), FakeClient(_pages(), _bodies()), now=NOW)

    saved = state.load(layout.state_path(tmp_path, PARTNER))
    assert saved[old_day] == seeded[old_day]
    assert DAY in saved


def test_run_reports_hour_coverage(tmp_path: Path) -> None:
    result = run(_config(tmp_path), FakeClient(_pages(), _bodies()), now=NOW)

    # The fixture day has kenn (2 files) and eutk (1 file): two station-days,
    # three hours of a possible 48, as an aggregate only — no day-level verdict.
    assert result.coverage.station_days == 2
    assert result.coverage.hours == 3
    assert result.coverage.possible == 48
    log_text = layout.log_path(tmp_path, PARTNER, result.runts).read_text()
    assert "coverage 20260710/kenn: 2/24" in log_text
    assert "coverage 20260710/eutk: 1/24" in log_text


def test_run_purges_state_and_files_past_retention(tmp_path: Path) -> None:
    # Seed a stale day in state and stale manifest/log files from ~190 days ago,
    # plus a recent one still inside the 65-day horizon.
    stale_day = "20260101"
    recent_day = "20260601"
    seeded = {
        stale_day: {"anfi": {"a.xml": {"mtime": "2026-01-01 00:00", "size": "1K"}}},
        recent_day: {"anfi": {"b.xml": {"mtime": "2026-06-01 00:00", "size": "1K"}}},
    }
    state.save(layout.state_path(tmp_path, PARTNER), seeded)
    stale_runts = "20260101T000000Z"
    recent_runts = "20260601T000000Z"
    for runts in (stale_runts, recent_runts):
        layout.default_manifest_path(tmp_path, PARTNER, runts).parent.mkdir(
            parents=True, exist_ok=True
        )
        layout.default_manifest_path(tmp_path, PARTNER, runts).write_text("{}\n")
        layout.log_path(tmp_path, PARTNER, runts).parent.mkdir(
            parents=True, exist_ok=True
        )
        layout.log_path(tmp_path, PARTNER, runts).write_text("x")

    result = run(_config(tmp_path), FakeClient(_pages(), _bodies()), now=NOW)

    saved = state.load(layout.state_path(tmp_path, PARTNER))
    # The stale day is purged from state; the recent one and this run's day stay.
    assert stale_day not in saved
    assert recent_day in saved
    assert DAY in saved
    # Stale run files are deleted; recent ones and this run's own files survive.
    assert not layout.default_manifest_path(tmp_path, PARTNER, stale_runts).exists()
    assert not layout.log_path(tmp_path, PARTNER, stale_runts).exists()
    assert layout.default_manifest_path(tmp_path, PARTNER, recent_runts).exists()
    assert layout.log_path(tmp_path, PARTNER, recent_runts).exists()
    assert layout.default_manifest_path(tmp_path, PARTNER, result.runts).exists()
    assert layout.log_path(tmp_path, PARTNER, result.runts).exists()


# --- ticket 11: availability discovery, input gate & dynamic retention -------


def test_tier1_discovery_fetch_failure_aborts_run(tmp_path: Path) -> None:
    # The root index keeps failing after retries: a total discovery failure aborts
    # the whole run before any sync work rather than syncing blindly.
    client = FakeClient(
        _pages(),
        _bodies(),
        text_errors={layout.root_url(): RuntimeError("503 exhausted")},
    )
    with pytest.raises(DiscoveryError):
        run(_config(tmp_path), client, now=NOW)
    assert client.downloaded == []


def test_tier1_zero_day_dirs_aborts_run(tmp_path: Path) -> None:
    # A root index that parses but holds no YYYYMMDD directory is a Tier-1 abort.
    pages = _pages()
    pages[layout.root_url()] = root_index(["notes", "logs"])
    with pytest.raises(DiscoveryError):
        run(_config(tmp_path), FakeClient(pages, _bodies()), now=NOW)


def test_named_day_too_old_hard_fails_before_listing(tmp_path: Path) -> None:
    # --date below the earliest available day fails before any listing; the day is
    # never fetched, so nothing is downloaded and no failure is counted.
    config = resolve_config([PARTNER, str(tmp_path), "--date", "20260101"], env={})
    client = FakeClient(_pages(), _bodies())
    with pytest.raises(GateError):
        run(config, client, now=NOW)
    assert client.downloaded == []


def test_named_future_day_hard_fails_before_listing(tmp_path: Path) -> None:
    # The upper edge fails too: a named day beyond `latest` cannot be delivered.
    config = resolve_config([PARTNER, str(tmp_path), "--date", "20260801"], env={})
    with pytest.raises(GateError):
        run(config, FakeClient(_pages(), _bodies()), now=NOW)


def test_incidental_tail_below_floor_is_dropped_and_rest_syncs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # --as-of 20260502 --days-back 3 → [0502, 0501, 0430, 0429]; the earliest
    # available day is 20260501, so 0430/0429 are an incidental tail: dropped with
    # one warning and never listed, while 0502/0501 sync normally.
    kept = ["20260502", "20260501"]
    config = resolve_config(
        [PARTNER, str(tmp_path), "--as-of", "20260502", "--days-back", "3"], env={}
    )
    client = FakeClient(_pages_for_days(kept), _bodies_for_days(kept))
    with caplog.at_level("WARNING", logger="swobml_sync"):
        result = run(config, client, now=NOW)

    assert result.days == kept
    # Dropped days never reach the ticket-04 failure path.
    assert result.failed == 0
    assert (result.added, result.changed) == (6, 0)
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "20260430" in warnings[0].getMessage()


def test_tier2_missing_today_syncs_but_skips_automatic_purge(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # The index's latest day is yesterday (today's dir not published yet). The run
    # still syncs today, but automatic purge is skipped — a missing today casts
    # doubt on the discovered horizon (fail-closed), so ancient state survives.
    stale_day = "20260101"
    seeded = {stale_day: {"anfi": {"a.xml": {"mtime": "m", "size": "1K"}}}}
    state.save(layout.state_path(tmp_path, PARTNER), seeded)

    pages = _pages()  # serves DAY = 20260710 (today) normally
    pages[layout.root_url()] = root_index(_day_span("20260501", "20260709"))
    config = resolve_config([PARTNER, str(tmp_path), "--days-back", "0"], env={})
    with caplog.at_level("INFO", logger="swobml_sync"):
        result = run(config, FakeClient(pages, _bodies()), now=NOW)

    assert result.days == [DAY]  # today still synced (incidental, not gated out)
    assert result.added == 3
    saved = state.load(layout.state_path(tmp_path, PARTNER))
    assert stale_day in saved  # automatic purge skipped, so it is retained
    assert any("skipping automatic purge" in r.getMessage() for r in caplog.records)


def test_truncated_index_clamps_auto_purge_to_thirty_day_floor(tmp_path: Path) -> None:
    # A truncated index reports a too-recent earliest (5 days back). The 30-day
    # floor clamps the horizon up so state inside 30 days is never auto-purged.
    protected = "20260620"  # 20 days old: newer than the floor, must survive
    ancient = "20260101"  # genuinely ancient: purged
    seeded = {
        protected: {"anfi": {"a.xml": {"mtime": "m", "size": "1K"}}},
        ancient: {"anfi": {"b.xml": {"mtime": "m", "size": "1K"}}},
    }
    state.save(layout.state_path(tmp_path, PARTNER), seeded)

    pages = _pages()
    pages[layout.root_url()] = root_index(_day_span("20260705", "20260710"))
    result = run(_config(tmp_path), FakeClient(pages, _bodies()), now=NOW)

    saved = state.load(layout.state_path(tmp_path, PARTNER))
    assert protected in saved  # protected by the 30-day floor despite earliest=0705
    assert ancient not in saved
    assert DAY in saved
    assert result.failed == 0


def test_explicit_retention_days_overrides_discovery_and_floor(tmp_path: Path) -> None:
    # --retention-days 5 bypasses discovery (earliest 20260501, which would keep
    # 20260601) and the 30-day floor, purging everything older than 5 days.
    recent = "20260601"
    seeded = {recent: {"anfi": {"a.xml": {"mtime": "m", "size": "1K"}}}}
    state.save(layout.state_path(tmp_path, PARTNER), seeded)

    config = resolve_config(
        [PARTNER, str(tmp_path), "--date", DAY, "--retention-days", "5"], env={}
    )
    run(config, FakeClient(_pages(), _bodies()), now=NOW)

    saved = state.load(layout.state_path(tmp_path, PARTNER))
    assert recent not in saved  # 39 days old > 5-day override → purged
    assert DAY in saved


def test_cli_returns_nonzero_on_tier1_discovery_failure(tmp_path: Path) -> None:
    client = FakeClient(
        _pages(),
        _bodies(),
        text_errors={layout.root_url(): RuntimeError("503 exhausted")},
    )
    code = cli.main([PARTNER, str(tmp_path), "--date", DAY], client=client)
    assert code == cli.EXIT_PREFLIGHT != 0


def test_cli_returns_nonzero_on_gate_failure(tmp_path: Path) -> None:
    code = cli.main(
        [PARTNER, str(tmp_path), "--date", "20260101"],
        client=FakeClient(_pages(), _bodies()),
    )
    assert code == cli.EXIT_PREFLIGHT != 0
