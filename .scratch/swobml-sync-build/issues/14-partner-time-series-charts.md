# 14 — Per-partner time-series charts

**What to build:** Enrich each partner card on the dashboard with **time-series
charts** drawn from the aggregate data model ticket 13 already produces. This is
a rendering-only addition: the parsing, globbing, and aggregation are done — this
ticket consumes the per-partner **full run series (sorted by `runts`)** the model
exposes and turns it into charts. No changes to how stats are read or modelled.

## Charts

- Per partner card, small **inline-SVG line charts** over that partner's run
  series, **one raw point per run** (no bucketing — the retention window that
  prunes `stats/*.json` already bounds the history):
  - **Requests** — listing vs downloads.
  - **Deltas** — added / changed / failed.
  - **Coverage %** — from the run's coverage aggregate.
- **Zero external/CDN dependencies**: hand-rolled inline SVG + CSS, no runtime
  deps added to `pyproject`, still one self-contained file that renders offline.
- **Load the `dataviz` skill** before writing chart code — colour, axes, legends,
  light/dark, and small-multiple layout should follow its guidance, and the
  charts must read as one consistent system across partners.

## Edge cases

- A partner with a **single run** (one point) still renders sensibly — a dot or a
  flat segment, not a crash or an empty box.
- A partner whose series is missing a metric (older stats file without a field)
  degrades gracefully rather than breaking the whole page (consistent with the
  fail-closed stance in 13).

## Docs

- **README**: note that the dashboard shows per-partner trends over the retained
  window (a line update to the command's description from ticket 13).

**Blocked by:** 13 — Dashboard skeleton + aggregate data model (this consumes the
per-partner series that ticket exposes and renders into its cards).

**Status:** ready-for-agent

- [ ] Each partner card renders inline-SVG line charts for requests (listing vs download), deltas (added/changed/failed), and coverage %, one raw point per run
- [ ] Charts are drawn purely from ticket 13's data model — no new parsing/globbing/aggregation
- [ ] Zero external dependencies; the page remains one self-contained offline file
- [ ] Single-run and missing-metric partners render sensibly, never crashing the page
- [ ] `dataviz` guidance applied so the charts read as one consistent system (colour, axes, legend, light/dark)
- [ ] README updated to mention the per-partner trends
- [ ] Tests cover: chart rendering for a multi-run partner, the single-run edge case, and graceful handling of a series missing a metric
