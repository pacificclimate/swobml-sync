"""A separate ``swobml-dashboard`` command that aggregates persisted run stats.

This tool never runs a sync. It reads the per-run stats files a sync persists —
one ``<dir>/<partner>/stats/<runts>.json`` per run (ticket 12) — across every
partner under one root and renders a single self-contained HTML dashboard that
opens offline anywhere.

The module is two layers with a clean seam between them:

*Aggregation* (:func:`aggregate`) globs ``<dir>/*/stats/*.json``, parses each
file fail-closed (a malformed or foreign file is skipped with a warning, never
fatal), and turns the tree into a typed :class:`Dashboard` model. Per partner it
holds the **complete run series sorted oldest→newest by ``runts``** (a
:class:`PartnerSeries` of :class:`RunRecord`), plus a ``latest`` view; across
partners it holds a :class:`Rollup` of each partner's latest run for the summary
header.

*Rendering* (:func:`render`) is a thin, pure function from that model to one HTML
string. The skeleton renders only each partner's **latest** numbers, but the
model already carries the full series so ticket 14 adds inline-SVG charts as a
pure rendering addition — no change to parsing or aggregation. **That model is
the documented contract handed to ticket 14**: consume :class:`PartnerSeries` and
its ``runs`` (already sorted), do not re-glob or re-parse.

Writing is atomic (:func:`write_dashboard`), so a failed render never leaves a
partial or broken HTML file behind.
"""

from __future__ import annotations

import argparse
import html
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from swobml_sync import layout
from swobml_sync.atomicio import write_atomic

log = logging.getLogger("swobml_sync.dashboard")


# --- the aggregate data model (the contract for ticket 14) ----------------


def _total_requests(listing_requests: int, downloads: int) -> int:
    """Total logical web requests: listings plus downloads. One place owns the
    "total is the sum" rule for both a single run and the cross-partner roll-up."""
    return listing_requests + downloads


def _coverage_pct(hours: int, possible: int) -> float | None:
    """Hour coverage as a percentage, or ``None`` when nothing is coverable
    (``possible == 0``), so callers show "—" rather than a misleading 0%. One
    place owns this so a run and the roll-up can never derive it differently."""
    return None if possible == 0 else 100.0 * hours / possible


@dataclass(frozen=True)
class RunRecord:
    """One run parsed from a partner's ``stats/<runts>.json`` — the point unit of
    a partner's time series and the row ticket 14 plots.

    ``requests`` (listing + downloads) and ``coverage_pct`` are derived on demand,
    never stored, mirroring the sync's own "total is the sum" stance (ticket 12).
    """

    runts: str
    listing_requests: int
    downloads: int
    added: int
    changed: int
    failed: int
    coverage_hours: int
    coverage_possible: int

    @property
    def requests(self) -> int:
        """Total logical web requests this run made: listings plus downloads."""
        return _total_requests(self.listing_requests, self.downloads)

    @property
    def coverage_pct(self) -> float | None:
        """Hour coverage as a percentage, or ``None`` for an empty run."""
        return _coverage_pct(self.coverage_hours, self.coverage_possible)


@dataclass(frozen=True)
class PartnerSeries:
    """One partner's complete run history, ``runs`` sorted oldest→newest by
    ``runts``. This full series is the seam ticket 14 charts; the skeleton reads
    only :attr:`latest`."""

    partner: str
    runs: list[RunRecord]

    @property
    def latest(self) -> RunRecord:
        """The newest run in the series (``runs`` is sorted, so the last one).

        A :class:`PartnerSeries` only ever exists with at least one run — a
        partner whose files all failed to parse is dropped from the model — so
        this never indexes an empty list.
        """
        return self.runs[-1]


@dataclass(frozen=True)
class Rollup:
    """Cross-partner roll-up of each partner's **latest** run, for the summary
    header. Coverage is aggregated as summed hours over summed possible, so a
    percentage is comparable across partners of different sizes."""

    partners: int
    listing_requests: int
    downloads: int
    added: int
    changed: int
    failed: int
    coverage_hours: int
    coverage_possible: int

    @property
    def requests(self) -> int:
        """Total logical web requests across every partner's latest run."""
        return _total_requests(self.listing_requests, self.downloads)

    @property
    def coverage_pct(self) -> float | None:
        """Aggregate hour coverage across all partners' latest runs, or ``None``
        when nothing is coverable."""
        return _coverage_pct(self.coverage_hours, self.coverage_possible)


@dataclass(frozen=True)
class Dashboard:
    """The full aggregate model: every partner's series (sorted by slug) plus the
    cross-partner roll-up. The single value handed from aggregation to rendering
    and the contract ticket 14 consumes."""

    partners: list[PartnerSeries]
    rollup: Rollup


# --- aggregation: glob, parse fail-closed, model --------------------------


def _as_int(value: object) -> int:
    """Coerce a parsed-JSON value to an ``int``, defaulting anything missing or
    non-numeric to 0 so one garbage or absent field never breaks a whole series."""
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def parse_run(path: Path) -> RunRecord | None:
    """Parse one ``stats/<runts>.json`` into a :class:`RunRecord`, fail-closed.

    The record shape mirrors the writer, :func:`swobml_sync.sync.run_record`, but
    this reader is deliberately decoupled from it: rather than sharing a schema it
    reads each key defensively so it survives files the current writer would never
    produce.

    Returns ``None`` — with a warning — for anything that is not a stats record:
    an unreadable or malformed file, or valid JSON that is not an object carrying
    a string ``runts`` (a foreign file dropped into ``stats/``). A genuine record
    that is merely missing a *metric* field still parses; the absent field
    degrades to 0 (see :func:`_as_int`), so an older stats file never breaks the
    partner's series.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("skipping unreadable stats file %s: %s", path, exc)
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("runts"), str):
        log.warning("skipping foreign JSON (no string runts) %s", path)
        return None
    coverage = raw.get("coverage")
    if not isinstance(coverage, dict):
        coverage = {}
    return RunRecord(
        runts=raw["runts"],
        listing_requests=_as_int(raw.get("listing_requests")),
        downloads=_as_int(raw.get("downloads")),
        added=_as_int(raw.get("added")),
        changed=_as_int(raw.get("changed")),
        failed=_as_int(raw.get("failed")),
        coverage_hours=_as_int(coverage.get("hours")),
        coverage_possible=_as_int(coverage.get("possible")),
    )


def aggregate(directory: Path) -> Dashboard:
    """Scan every partner's ``stats/`` dir under ``directory`` into a :class:`Dashboard`.

    Each immediate subdirectory of ``directory`` is a partner; its per-run files
    live in ``layout.stats_dir(directory, partner)`` — the tree shape stays owned
    by :mod:`swobml_sync.layout`, never hand-built here. Malformed and foreign
    files are skipped (see :func:`parse_run`); a partner whose files all fail to
    parse, or that has no ``stats/`` dir, contributes no series at all. A missing
    root is not an error (fail-closed: it models to an empty dashboard). Partners
    come out sorted by slug and each partner's runs oldest→newest by ``runts``.
    """
    partners: list[PartnerSeries] = []
    for partner_dir in _partner_dirs(directory):
        stats_dir = layout.stats_dir(directory, partner_dir.name)
        if not stats_dir.is_dir():
            continue
        runs = [
            record
            for path in sorted(stats_dir.glob("*.json"))
            if (record := parse_run(path)) is not None
        ]
        if runs:
            runs.sort(key=lambda r: r.runts)
            partners.append(PartnerSeries(partner=partner_dir.name, runs=runs))
    return Dashboard(partners=partners, rollup=_rollup(partners))


def _partner_dirs(directory: Path) -> list[Path]:
    """The candidate partner subdirectories under a root, sorted by slug.

    A missing or non-directory root yields nothing rather than raising, so a
    dashboard over an empty or absent tree still renders its empty state."""
    if not directory.is_dir():
        return []
    return sorted((p for p in directory.iterdir() if p.is_dir()), key=lambda p: p.name)


def _rollup(partners: list[PartnerSeries]) -> Rollup:
    """Sum each partner's latest run into the cross-partner header figure."""
    latest = [p.latest for p in partners]
    return Rollup(
        partners=len(partners),
        listing_requests=sum(r.listing_requests for r in latest),
        downloads=sum(r.downloads for r in latest),
        added=sum(r.added for r in latest),
        changed=sum(r.changed for r in latest),
        failed=sum(r.failed for r in latest),
        coverage_hours=sum(r.coverage_hours for r in latest),
        coverage_possible=sum(r.coverage_possible for r in latest),
    )


# --- rendering: a thin, pure layer over the model -------------------------

_STYLE = """
:root { color-scheme: light dark; --bg:#f6f7f9; --card:#fff; --ink:#1a1d21;
  --muted:#5b6470; --line:#e3e6ea; --accent:#2563eb; }
@media (prefers-color-scheme: dark) { :root { --bg:#14171a; --card:#1d2125;
  --ink:#e8eaed; --muted:#9aa4b0; --line:#2c3238; --accent:#5b9bff; } }
* { box-sizing: border-box; }
body { margin:0; padding:2rem 1.5rem; background:var(--bg); color:var(--ink);
  font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }
.wrap { max-width:1100px; margin:0 auto; }
h1 { font-size:1.4rem; margin:0 0 1.25rem; }
.summary { display:flex; flex-wrap:wrap; gap:1.5rem; padding:1rem 1.25rem;
  background:var(--card); border:1px solid var(--line); border-radius:12px;
  margin-bottom:1.75rem; }
.summary .stat { display:flex; flex-direction:column; }
.stat .value { font-size:1.5rem; font-weight:650; }
.stat .label { font-size:.72rem; text-transform:uppercase; letter-spacing:.04em;
  color:var(--muted); }
.cards { display:grid; gap:1.25rem;
  grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px;
  padding:1.1rem 1.25rem; }
.card h2 { font-size:1.05rem; margin:0 0 .15rem; }
.card .runts { font-size:.75rem; color:var(--muted); margin:0 0 .9rem;
  font-variant-numeric:tabular-nums; }
.card-stats { display:grid; grid-template-columns:1fr 1fr; gap:.6rem 1rem; margin:0; }
.card-stats div { display:flex; flex-direction:column; }
.card-stats .value { font-size:1.15rem; font-weight:600;
  font-variant-numeric:tabular-nums; }
.card-stats .label { font-size:.7rem; text-transform:uppercase; letter-spacing:.03em;
  color:var(--muted); }
.charts:empty { display:none; }
.empty { padding:3rem 1.5rem; text-align:center; color:var(--muted);
  background:var(--card); border:1px dashed var(--line); border-radius:12px; }
""".strip()


def _pct(value: float | None) -> str:
    """A coverage percentage for display, or an em dash when undefined."""
    return "—" if value is None else f"{value:.0f}%"


def _summary(rollup: Rollup) -> str:
    """The compact cross-partner header: latest run per partner, totalled."""
    stats = [
        (str(rollup.partners), "Partners"),
        (str(rollup.requests), "Requests"),
        (str(rollup.downloads), "Downloads"),
        (str(rollup.added), "Added"),
        (str(rollup.changed), "Changed"),
        (str(rollup.failed), "Failed"),
        (_pct(rollup.coverage_pct), "Coverage"),
    ]
    cells = "".join(
        f'<div class="stat"><span class="value">{html.escape(v)}</span>'
        f'<span class="label">{html.escape(l)}</span></div>'
        for v, l in stats
    )
    return f'<section class="summary">{cells}</section>'


def _card(series: PartnerSeries) -> str:
    """One partner card of its latest numbers, with an empty ``charts`` home for
    ticket 14 to fill without touching this layout."""
    run = series.latest
    figures = [
        (str(run.listing_requests), "Listing req"),
        (str(run.downloads), "Downloads"),
        (str(run.added), "Added"),
        (str(run.changed), "Changed"),
        (str(run.failed), "Failed"),
        (_pct(run.coverage_pct), "Coverage"),
    ]
    cells = "".join(
        f'<div><span class="value">{html.escape(v)}</span>'
        f'<span class="label">{html.escape(l)}</span></div>'
        for v, l in figures
    )
    return (
        '<article class="card">'
        f"<h2>{html.escape(series.partner)}</h2>"
        f'<p class="runts">latest run {html.escape(run.runts)}</p>'
        f'<div class="card-stats">{cells}</div>'
        # Ticket 14 fills this with per-partner inline-SVG charts; empty here so
        # the CSS hides it and the skeleton renders clean.
        '<div class="charts"></div>'
        "</article>"
    )


def render(model: Dashboard) -> str:
    """Render the model to one self-contained HTML string (inline CSS, no external
    dependencies). A model with no partners renders a valid empty-state page."""
    if not model.partners:
        body = '<p class="empty">No run stats found under this directory yet.</p>'
    else:
        cards = "".join(_card(p) for p in model.partners)
        body = f'{_summary(model.rollup)}<div class="cards">{cards}</div>'
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>swobml-sync dashboard</title>"
        f"<style>{_STYLE}</style></head><body>"
        f'<div class="wrap"><h1>swobml-sync dashboard</h1>{body}</div>'
        "</body></html>\n"
    )


def write_dashboard(path: Path, model: Dashboard) -> None:
    """Render and write the dashboard to ``path`` atomically.

    Rendering is done wholly in memory before the write, and the write is a
    temp-then-rename (see :mod:`swobml_sync.atomicio`), so ``path`` is only ever
    replaced by a complete file — a partial or broken HTML file is never left.
    """
    write_atomic(path, render(model).encode("utf-8"))


# --- CLI ------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the ``swobml-dashboard`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="swobml-dashboard",
        description=(
            "Aggregate the per-run stats files a sync persists under one root "
            "(<dir>/<partner>/stats/*.json) into a self-contained HTML dashboard."
        ),
    )
    parser.add_argument(
        "directory",
        metavar="dir",
        help="root the sync writes under; every <dir>/<partner>/stats is scanned",
    )
    parser.add_argument(
        "--out",
        metavar="PATH",
        default=None,
        help="dashboard HTML path (default <dir>/dashboard.html)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Aggregate ``<dir>`` and write the dashboard; exit 0 including empty roots.

    Configures logging so the fail-closed skip warnings from :func:`parse_run`
    reach stderr, then aggregates and writes atomically. An empty root still
    produces a valid empty-state page and exits 0.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = build_parser()
    ns = parser.parse_args(argv)

    directory = Path(ns.directory)
    out = Path(ns.out) if ns.out else directory / "dashboard.html"

    model = aggregate(directory)
    write_dashboard(out, model)
    log.info("wrote dashboard for %d partner(s) to %s", len(model.partners), out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
