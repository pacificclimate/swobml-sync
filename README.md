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
| `--retention-days N`| `SWOBML_RETENTION_DAYS` | `65`    | Purge state/manifests/logs older than N days.                 |
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
  .sync-state.json               what has been downloaded (day → station → file)
```

stdout is a single JSON summary line, `{manifest, added, changed, failed, days}`;
progress and warnings go to stderr. A re-run downloads only files that are new
or whose upstream `(last-modified, size)` changed, so running twice against an
unchanged source downloads nothing and writes an empty manifest.

## Development

```
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python -m pytest
.venv/bin/python -m mypy
```
