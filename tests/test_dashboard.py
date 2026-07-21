"""Tests for the stats dashboard: the pure aggregation layer and its rendering.

The aggregation layer is pure over the on-disk ``<dir>/<partner>/stats/*.json``
tree, so these exercise it directly without running a sync. It is the documented
contract ticket 14 charts, so the shape it produces is asserted here in full.
"""

from __future__ import annotations

import json
from pathlib import Path

from swobml_sync import dashboard


def _write_stats(
    directory: Path,
    partner: str,
    runts: str,
    *,
    listing_requests: int = 0,
    downloads: int = 0,
    added: int = 0,
    changed: int = 0,
    failed: int = 0,
    hours: int = 0,
    possible: int = 0,
    days: list[str] | None = None,
) -> Path:
    """Write one ``stats/<runts>.json`` exactly as a run persists it."""
    path = directory / partner / "stats" / f"{runts}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "runts": runts,
        "added": added,
        "changed": changed,
        "failed": failed,
        "days": days or [],
        "coverage": {"station_days": 0, "hours": hours, "possible": possible},
        "listing_requests": listing_requests,
        "downloads": downloads,
    }
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    return path


# --- aggregation: discovery, grouping, ordering ---------------------------


def test_aggregate_discovers_every_partner_under_the_root(tmp_path: Path) -> None:
    _write_stats(tmp_path, "nb-firewx", "20260710T000000Z")
    _write_stats(tmp_path, "on-fire", "20260710T000000Z")
    model = dashboard.aggregate(tmp_path)
    # Partners come from the subdirectory names, sorted, one series each.
    assert [p.partner for p in model.partners] == ["nb-firewx", "on-fire"]


def test_aggregate_orders_a_partners_runs_oldest_to_newest(tmp_path: Path) -> None:
    _write_stats(tmp_path, "nb-firewx", "20260710T120000Z")
    _write_stats(tmp_path, "nb-firewx", "20260709T000000Z")
    _write_stats(tmp_path, "nb-firewx", "20260710T000000Z")
    (series,) = dashboard.aggregate(tmp_path).partners
    assert [r.runts for r in series.runs] == [
        "20260709T000000Z",
        "20260710T000000Z",
        "20260710T120000Z",
    ]
    # The latest view is the newest run in the series.
    assert series.latest.runts == "20260710T120000Z"


def test_aggregate_parses_every_modelled_field(tmp_path: Path) -> None:
    _write_stats(
        tmp_path,
        "nb-firewx",
        "20260710T000000Z",
        listing_requests=5,
        downloads=7,
        added=3,
        changed=2,
        failed=1,
        hours=12,
        possible=24,
    )
    run = dashboard.aggregate(tmp_path).partners[0].latest
    assert (run.listing_requests, run.downloads) == (5, 7)
    assert (run.added, run.changed, run.failed) == (3, 2, 1)
    # Total requests is derived from the two counters, never stored.
    assert run.requests == 12
    # Coverage percent is hours / possible.
    assert run.coverage_pct == 50.0


def test_aggregate_empty_root_has_no_partners(tmp_path: Path) -> None:
    model = dashboard.aggregate(tmp_path)
    assert model.partners == []
    # The roll-up over nothing is all zeros across zero partners.
    assert model.rollup.partners == 0
    assert model.rollup.requests == 0


# --- aggregation: fail-closed parsing -------------------------------------


def test_aggregate_skips_malformed_json_with_a_warning(tmp_path: Path) -> None:
    _write_stats(tmp_path, "nb-firewx", "20260710T000000Z", downloads=4)
    bad = tmp_path / "nb-firewx" / "stats" / "20260711T000000Z.json"
    bad.write_text("{not valid json", encoding="utf-8")
    model = dashboard.aggregate(tmp_path)
    # The good run survives; the malformed file is silently dropped, not fatal.
    (series,) = model.partners
    assert [r.runts for r in series.runs] == ["20260710T000000Z"]


def test_aggregate_skips_foreign_json_without_a_runts(tmp_path: Path) -> None:
    _write_stats(tmp_path, "nb-firewx", "20260710T000000Z")
    foreign = tmp_path / "nb-firewx" / "stats" / "note.json"
    foreign.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
    an_array = tmp_path / "nb-firewx" / "stats" / "list.json"
    an_array.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    (series,) = dashboard.aggregate(tmp_path).partners
    assert [r.runts for r in series.runs] == ["20260710T000000Z"]


def test_aggregate_defaults_missing_metric_fields_to_zero(tmp_path: Path) -> None:
    # An older stats file that predates a metric still parses; the absent field
    # degrades to 0 rather than breaking the partner's whole series.
    path = tmp_path / "nb-firewx" / "stats" / "20260710T000000Z.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"runts": "20260710T000000Z"}), encoding="utf-8")
    run = dashboard.aggregate(tmp_path).partners[0].latest
    assert run.listing_requests == 0
    assert run.downloads == 0
    # Coverage with no possible hours has no meaningful percent.
    assert run.coverage_pct is None


def test_aggregate_drops_a_partner_with_no_valid_runs(tmp_path: Path) -> None:
    bad = tmp_path / "ghost" / "stats" / "20260710T000000Z.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("garbage", encoding="utf-8")
    assert dashboard.aggregate(tmp_path).partners == []


# --- aggregation: the cross-partner roll-up -------------------------------


def test_rollup_totals_each_partners_latest_run(tmp_path: Path) -> None:
    # nb-firewx: an older run then a newer one — only the newer counts.
    _write_stats(tmp_path, "nb-firewx", "20260709T000000Z", downloads=99)
    _write_stats(
        tmp_path,
        "nb-firewx",
        "20260710T000000Z",
        listing_requests=2,
        downloads=3,
        added=1,
        hours=12,
        possible=24,
    )
    _write_stats(
        tmp_path,
        "on-fire",
        "20260710T000000Z",
        listing_requests=4,
        downloads=1,
        changed=2,
        hours=6,
        possible=24,
    )
    rollup = dashboard.aggregate(tmp_path).rollup
    assert rollup.partners == 2
    # Sums are over each partner's latest run only, so the 99 never appears.
    assert rollup.listing_requests == 6
    assert rollup.downloads == 4
    assert rollup.requests == 10
    assert rollup.added == 1
    assert rollup.changed == 2
    # Aggregate coverage is summed hours over summed possible: 18 / 48.
    assert rollup.coverage_pct == 37.5


# --- rendering: a thin layer over the model -------------------------------


def test_render_embeds_the_modelled_latest_values(tmp_path: Path) -> None:
    _write_stats(
        tmp_path, "nb-firewx", "20260709T000000Z", downloads=99  # older, ignored
    )
    _write_stats(
        tmp_path,
        "nb-firewx",
        "20260710T000000Z",
        listing_requests=5,
        downloads=7,
        added=3,
        changed=2,
        failed=1,
        hours=12,
        possible=24,
    )
    html_out = dashboard.render(dashboard.aggregate(tmp_path))
    # One self-contained document, no external/CDN dependencies.
    assert html_out.startswith("<!doctype html>")
    assert "http://" not in html_out and "https://" not in html_out
    assert (
        "<style>" in html_out and "<link" not in html_out and "<script" not in html_out
    )
    # The partner card shows its latest numbers, not the superseded older run.
    assert "nb-firewx" in html_out
    assert "20260710T000000Z" in html_out
    assert ">99<" not in html_out  # the older run's downloads never render
    for value in (">5<", ">7<", ">3<", ">2<", ">1<", "50%"):
        assert value in html_out


def test_render_empty_model_is_a_valid_empty_state() -> None:
    html_out = dashboard.render(
        dashboard.Dashboard(partners=[], rollup=_empty_rollup())
    )
    assert html_out.startswith("<!doctype html>")
    assert html_out.rstrip().endswith("</html>")
    assert "No run stats" in html_out


def test_render_escapes_a_partner_slug() -> None:
    run = dashboard.RunRecord("20260710T000000Z", 0, 0, 0, 0, 0, 0, 0)
    series = dashboard.PartnerSeries("<script>x", [run])
    html_out = dashboard.render(
        dashboard.Dashboard(partners=[series], rollup=_empty_rollup())
    )
    assert "<script>x" not in html_out
    assert "&lt;script&gt;x" in html_out


def _empty_rollup() -> dashboard.Rollup:
    return dashboard.Rollup(0, 0, 0, 0, 0, 0, 0, 0)


# --- CLI: writing, defaults, exit codes -----------------------------------


def test_main_writes_dashboard_and_exits_zero(tmp_path: Path) -> None:
    _write_stats(tmp_path, "nb-firewx", "20260710T000000Z", downloads=4)
    rc = dashboard.main([str(tmp_path)])
    assert rc == 0
    out = tmp_path / "dashboard.html"
    assert out.exists()
    assert "nb-firewx" in out.read_text(encoding="utf-8")


def test_main_honours_out_override(tmp_path: Path) -> None:
    _write_stats(tmp_path, "nb-firewx", "20260710T000000Z")
    out = tmp_path / "sub" / "report.html"
    rc = dashboard.main([str(tmp_path), "--out", str(out)])
    assert rc == 0
    assert out.exists()
    assert not (tmp_path / "dashboard.html").exists()


def test_main_empty_root_writes_valid_page_and_exits_zero(tmp_path: Path) -> None:
    rc = dashboard.main([str(tmp_path)])
    assert rc == 0
    out = tmp_path / "dashboard.html"
    assert out.exists()
    assert "No run stats" in out.read_text(encoding="utf-8")


def test_main_never_leaves_partial_html_on_a_prior_file(tmp_path: Path) -> None:
    # An earlier good dashboard must not be replaced by anything partial. The
    # write is atomic, so a re-run over an empty root replaces it whole.
    out = tmp_path / "dashboard.html"
    out.write_text("STALE", encoding="utf-8")
    dashboard.main([str(tmp_path), "--out", str(out)])
    text = out.read_text(encoding="utf-8")
    assert "STALE" not in text
    assert text.startswith("<!doctype html>")
