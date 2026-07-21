# 13 — Stats dashboard: skeleton tool + aggregate data-model contract

**What to build:** A **separate** command that reads the per-run stats files
written by ticket 12 across every partner under one root and renders a
self-contained HTML dashboard. This ticket delivers the walking skeleton **and,
deliberately, the full aggregate data model** — the explicit contract ticket 14
builds its charts on. The skeleton only *renders* latest numbers, but it *parses
and models* each partner's complete run history so ticket 14 adds charts without
touching parsing or aggregation.

## Invocation

- New console script **`swobml-dashboard <dir> --out <path>`** in a new
  `swobml_sync.dashboard` module, registered in `[project.scripts]`. Default
  `--out` is `<dir>/dashboard.html`.
- **Scans one root:** globs `<dir>/*/stats/*.json` to discover every partner and
  its runs — the same `<dir>` the sync writes under, partner slug per subdir.
- **Fail-closed:** a malformed or foreign JSON file is skipped with a warning,
  never fatal. A root with no stats renders a valid **empty-state** page and
  exits 0. The tool never writes a partial/broken HTML file.

## Aggregate data model (the contract for ticket 14)

- A **pure aggregation layer**, separate from any HTML, turns the globbed files
  into a typed model and is what the tests assert on:
  - Per partner: the **complete list of run records** parsed from `stats/*.json`,
    **sorted by `runts`** — each record carrying `runts`, `listing_requests`,
    `downloads` (and derived total), `added`, `changed`, `failed`, and coverage.
  - Per partner: a **latest-run** view and whatever **totals/aggregates** the
    summary header needs.
  - A cross-partner roll-up for the summary header.
- Model the **full series now even though the skeleton renders only the latest**,
  so ticket 14 is purely a rendering addition. Keep the model documented (its
  shape is the seam handed to 14).

## Rendering (skeleton)

- Emit **one self-contained static HTML file**: inline CSS, **zero external/CDN
  dependencies**, no runtime deps added to `pyproject`. Renders offline anywhere.
- **Split rendering from aggregation**: `data model → HTML` is a thin layer over
  the tested model.
- Layout: a compact **cross-partner summary header** (latest run per partner,
  totalled), then **one card per partner** showing that partner's **latest**
  numbers (requests split listing/download, added/changed/failed, coverage %).
  Leave the card an obvious home for the charts ticket 14 will add.

## Docs

- **README**: document the `swobml-dashboard` command, its root-scanning
  behaviour, and the `--out` default.
- If the data-model shape is worth pinning down for the next agent, add a short
  note (module docstring is fine) describing the model 14 consumes.

**Blocked by:** 12 — Request stats (needs `stats/<runts>.json` files on disk to
aggregate).

**Status:** done

- [x] `swobml-dashboard <dir> --out <path>` exists as its own console script over a new `dashboard` module
- [x] It globs `<dir>/*/stats/*.json`, discovering every partner and run under the root
- [x] Malformed/foreign JSON is skipped with a warning; an empty root renders a valid empty page and exits 0; no partial HTML is ever written
- [x] A pure, unit-tested aggregation layer produces the per-partner **full run series (sorted by runts)** plus latest-run and total views, and a cross-partner roll-up — this is the documented contract for ticket 14
- [x] Rendering is a thin layer over the model; output is one self-contained HTML file with inline CSS and zero external dependencies
- [x] The page shows a cross-partner summary header and one per-partner card of latest numbers, with room for charts
- [x] README documents the command; the data-model shape is noted for the next agent
- [x] Tests cover: globbing/partner discovery, skip of malformed files, empty-state, the full-series aggregation, and that the HTML embeds the modelled values
