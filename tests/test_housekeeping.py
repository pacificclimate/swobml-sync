"""End-of-run housekeeping: hour-coverage counting and retention purge.

Both halves are pure over an in-memory sync state and the on-disk run files, so
these exercise them directly without the network or a full run.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from swobml_sync import housekeeping, layout
from swobml_sync.state import SyncState

RUN_DATE = date(2026, 7, 10)


def _state() -> SyncState:
    """A state with two processed days and a stale one outside the window."""

    def hours(n: int) -> dict[str, dict[str, str]]:
        return {f"file{i}.xml": {"mtime": "m", "size": "s"} for i in range(n)}

    return {
        "20260710": {"kenn": hours(2), "eutk": hours(24)},
        "20260709": {"kenn": hours(3)},
        "20260101": {"anfi": hours(5)},
    }


def test_day_coverages_count_files_per_station() -> None:
    coverages = housekeeping.day_coverages(_state(), ["20260710"])
    # Stations are reported sorted; coverage is the file count, capped conceptually
    # at 24, drawn straight from state without parsing hours out of filenames.
    assert coverages == [
        housekeeping.Coverage("20260710", "eutk", 24),
        housekeeping.Coverage("20260710", "kenn", 2),
    ]


def test_day_coverages_only_cover_processed_days() -> None:
    # A day sitting in state but outside the run's window contributes nothing.
    coverages = housekeeping.day_coverages(_state(), ["20260710"])
    assert all(c.day == "20260710" for c in coverages)


def test_day_coverages_cap_hours_at_a_full_day() -> None:
    # Even if state somehow holds more than 24 files, coverage never exceeds 24/24
    # so the aggregate's hours can't outrun its possible ceiling.
    files = {f"file{i}.xml": {"mtime": "m", "size": "s"} for i in range(30)}
    coverages = housekeeping.day_coverages({"20260710": {"kenn": files}}, ["20260710"])
    assert coverages == [housekeeping.Coverage("20260710", "kenn", 24)]


def test_aggregate_sums_hours_over_station_days() -> None:
    coverages = housekeeping.day_coverages(_state(), ["20260710", "20260709"])
    summary = housekeeping.aggregate(coverages)
    # Three station-days: eutk(24) + kenn(2) on the 10th, kenn(3) on the 9th.
    assert summary == housekeeping.CoverageSummary(
        station_days=3, hours=29, possible=72
    )


def test_aggregate_of_nothing_is_zero() -> None:
    assert housekeeping.aggregate([]) == housekeeping.CoverageSummary(0, 0, 0)


def test_report_coverage_logs_each_station(caplog) -> None:  # type: ignore[no-untyped-def]
    with caplog.at_level("INFO", logger="swobml_sync"):
        summary = housekeeping.report_coverage(_state(), ["20260710"])
    assert "coverage 20260710/eutk: 24/24" in caplog.text
    assert "coverage 20260710/kenn: 2/24" in caplog.text
    assert summary.hours == 26


def test_auto_retention_reaches_back_to_the_earliest_available_day() -> None:
    # The discovered horizon is exactly today − earliest, so automatic purge drops
    # state older than the earliest still-retrievable day.
    assert housekeeping.auto_retention_days(RUN_DATE, date(2026, 5, 1)) == 70


def test_auto_retention_clamps_up_to_the_thirty_day_floor() -> None:
    # However recent discovery's "earliest" comes back, the horizon never drops
    # below 30 days, so recent state is never auto-purged on a truncated index.
    assert housekeeping.auto_retention_days(RUN_DATE, date(2026, 7, 5)) == 30
    assert housekeeping.MIN_AUTO_RETENTION_DAYS == 30


def test_purge_state_drops_days_past_the_horizon() -> None:
    state = _state()
    purged = housekeeping.purge_state(state, RUN_DATE, retention_days=65)
    # The Jan day is ~190 days old, well beyond 65; the window days survive.
    assert purged == ["20260101"]
    assert "20260101" not in state
    assert set(state) == {"20260710", "20260709"}


def test_purge_state_keeps_the_exact_horizon_day() -> None:
    # A day exactly retention_days old is "not older than" the horizon: kept.
    state: SyncState = {"20260506": {"kenn": {}}, "20260505": {"kenn": {}}}
    purged = housekeeping.purge_state(state, RUN_DATE, retention_days=65)
    assert purged == ["20260505"]
    assert set(state) == {"20260506"}


def test_purge_state_leaves_malformed_keys_alone() -> None:
    state: SyncState = {"not-a-day": {"kenn": {}}, "20260101": {"anfi": {}}}
    purged = housekeeping.purge_state(state, RUN_DATE, retention_days=65)
    assert purged == ["20260101"]
    assert "not-a-day" in state


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")


def test_purge_run_files_deletes_old_manifests_logs_and_stats(tmp_path: Path) -> None:
    partner = "nb-firewx"
    old = "20260101T000000Z"
    recent = "20260709T120000Z"
    manifests = layout.manifests_dir(tmp_path, partner)
    logs = layout.logs_dir(tmp_path, partner)
    stats = layout.stats_dir(tmp_path, partner)
    _touch(manifests / f"{old}.jsonl")
    _touch(manifests / f"{recent}.jsonl")
    _touch(logs / f"{old}.log")
    _touch(logs / f"{recent}.log")
    _touch(stats / f"{old}.json")
    _touch(stats / f"{recent}.json")

    removed = housekeeping.purge_run_files(
        tmp_path, partner, RUN_DATE, retention_days=65
    )

    # Stats files age out on the same horizon as manifests and logs.
    assert {p.name for p in removed} == {f"{old}.jsonl", f"{old}.log", f"{old}.json"}
    assert not (manifests / f"{old}.jsonl").exists()
    assert (manifests / f"{recent}.jsonl").exists()
    assert not (logs / f"{old}.log").exists()
    assert (logs / f"{recent}.log").exists()
    assert not (stats / f"{old}.json").exists()
    assert (stats / f"{recent}.json").exists()


def test_purge_run_files_ignores_foreign_names(tmp_path: Path) -> None:
    partner = "nb-firewx"
    logs = layout.logs_dir(tmp_path, partner)
    _touch(logs / "README.txt")
    _touch(logs / "20260101T000000Z.log")

    removed = housekeeping.purge_run_files(
        tmp_path, partner, RUN_DATE, retention_days=65
    )

    assert {p.name for p in removed} == {"20260101T000000Z.log"}
    assert (logs / "README.txt").exists()


def test_purge_run_files_tolerates_missing_dirs(tmp_path: Path) -> None:
    # A partner that has never written a manifest or log yet is not an error.
    assert housekeeping.purge_run_files(tmp_path, "brand-new", RUN_DATE, 65) == []
