# swobml-sync

Syncs one swob-ml **partner**'s hourly observation files from the ECCC HPFX
server down to a local directory tree, tracking what has been seen so a re-run
picks up files that were previously unavailable, and emitting a **manifest** of
the run's changes for a downstream ingestion program.

See [CONTEXT.md](CONTEXT.md) for the domain glossary and [docs/adr/](docs/adr/)
for the architectural decisions.

## Usage

```
swobml-sync <partner> <dir> [options]
```

| Argument / flag     | Env var                 | Default | Meaning                                                       |
| ------------------- | ----------------------- | ------- | ------------------------------------------------------------- |
| `partner`           | `SWOBML_PARTNER`        | —       | Partner slug to sync (required).                              |
| `dir`               | `SWOBML_DIR`            | —       | Output directory (required).                                  |
| `--days-back N`     | `SWOBML_DAYS_BACK`      | `2`     | Rolling lookback window: today plus the previous N days (UTC).|
| `--date YYYYMMDD`   | `SWOBML_DATE`           | —       | Sync exactly these days; replaces the window. Repeatable.     |
| `--as-of YYYYMMDD`  | `SWOBML_AS_OF`          | today   | Anchor the window's newest day here; `--days-back` counts back from it. Ignored (with a warning) when `--date` is given. |
| `--retention-days N`| `SWOBML_RETENTION_DAYS` | discovered | Purge state/manifests/logs older than N days. Overrides the server-discovered horizon (floored at 30 days). |
| `--workers N`       | `SWOBML_WORKERS`        | `8`     | Download/discovery thread-pool size.                          |
| `--manifest PATH`   | `SWOBML_MANIFEST`       | —       | Override the default manifest location.                       |
| `--log-level LEVEL` | `SWOBML_LOG_LEVEL`      | `INFO`  | Logging level.                                                |

Every flag can be supplied via its `SWOBML_*` environment variable; an explicit
command-line argument wins when both are present.

## Output

A run writes everything under `<dir>/<partner>/`:

```
<dir>/<partner>/
  cache/<day>/<station>/<file>   downloaded SWOB files
  manifests/<runts>.jsonl        this run's added/changed files (always written)
  stats/<runts>.json             this run's request counts + outcome (see below)
  .sync-state.json               what has been downloaded (day → station → file)
```

stdout is a single JSON summary line,
`{runts, added, changed, failed, days, coverage, listing_requests, downloads, manifest}`;
progress and warnings go to stderr. `listing_requests` counts every
directory-index fetch (availability discovery plus each day and station index)
and `downloads` counts every SWOB file fetch — both **logical** requests, so the
retries inside the HTTP client stay invisible. The same record (minus the local
`manifest` path) is persisted per run to `stats/<runts>.json` for a separate
dashboard tool to aggregate; stats files age out on the same retention horizon as
manifests and logs. A re-run downloads only files that are new or whose upstream
`(last-modified, size)` changed, so running twice against an unchanged source
downloads nothing and writes an empty manifest.

## Dashboard

A separate command aggregates the per-run `stats/<runts>.json` files across every
partner under one root into a single self-contained HTML page:

```
swobml-dashboard <dir> [--out PATH]
```

It **scans one root** — the same `<dir>` the sync writes under — globbing
`<dir>/*/stats/*.json` to discover every partner (one per subdirectory) and its
runs. `--out` defaults to `<dir>/dashboard.html`. The page is one offline file
with inline CSS and **zero external dependencies**: a cross-partner summary header
(each partner's latest run, totalled) and one card per partner showing its latest
request counts, added/changed/failed, and coverage.

It is **fail-closed**: a malformed or foreign JSON file under `stats/` is skipped
with a warning, never fatal; a root with no stats renders a valid empty page and
exits 0; and the HTML is written atomically, so a partial or broken file is never
left behind. The command never runs a sync — it only reads what runs have already
persisted. (The aggregation layer models each partner's *complete* run series, not
just the latest; see the `swobml_sync.dashboard` module docstring for the model
shape.)

## Development

```
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python -m pytest
.venv/bin/python -m mypy
```
