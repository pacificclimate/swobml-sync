"""Tests for URL and local-path layout."""

from __future__ import annotations

from pathlib import Path

from swobml_sync import layout


def test_day_url_repeats_the_day() -> None:
    url = layout.day_url("nb-firewx", "20260710")
    assert url == (
        "https://hpfx.collab.science.gc.ca/20260710/WXO-DD/observations/"
        "swob-ml/partners/nb-firewx/20260710/"
    )


def test_station_url_extends_the_day_url() -> None:
    assert layout.station_url("nb-firewx", "20260710", "anfi") == (
        layout.day_url("nb-firewx", "20260710") + "anfi/"
    )


def test_file_url_extends_the_station_url() -> None:
    assert layout.file_url("nb-firewx", "20260710", "anfi", "a-swob.xml") == (
        layout.station_url("nb-firewx", "20260710", "anfi") + "a-swob.xml"
    )


def test_local_file_path_under_partner_cache() -> None:
    p = layout.local_file_path(
        Path("/data"), "nb-firewx", "20260710", "anfi", "a-swob.xml"
    )
    assert p == Path("/data/nb-firewx/cache/20260710/anfi/a-swob.xml")


def test_relative_path_is_relative_to_dir() -> None:
    rel = layout.relative_file_path("nb-firewx", "20260710", "anfi", "a-swob.xml")
    assert rel == "nb-firewx/cache/20260710/anfi/a-swob.xml"


def test_state_path_is_hidden_per_partner_file() -> None:
    assert layout.state_path(Path("/data"), "nb-firewx") == Path(
        "/data/nb-firewx/.sync-state.json"
    )


def test_default_manifest_path_uses_runts() -> None:
    assert layout.default_manifest_path(
        Path("/data"), "nb-firewx", "20260710T142530Z"
    ) == Path("/data/nb-firewx/manifests/20260710T142530Z.jsonl")
