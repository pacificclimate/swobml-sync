# swobml-sync

Syncs one swob-ml **partner**'s hourly observation files from the ECCC HPFX
server down to a local directory tree, tracking what has been seen so a re-run
picks up files that were previously unavailable, and emitting a **manifest** of
the run's changes for a downstream ingestion program.

## Language

### Source domain

**Partner**:
An upstream data provider whose observations are published under its own slug
(e.g. `nb-firewx`). Exactly one partner is synced per run, named on the command
line. Identity is the directory slug, used verbatim.
_Avoid_: provider, source, feed, vendor

**Station**:
A single observation site belonging to a partner, identified by its directory
slug (e.g. `anfi`). The set of stations for a day is discovered from the server,
not configured, and may grow as a day progresses.
_Avoid_: site, sensor, location

**Day**:
A UTC calendar date (`YYYYMMDD`) that partitions the source tree. The date
appears twice in the source path and is always the same value. All date logic —
"today", the window, `--date` — is computed in UTC to match this partitioning.
_Avoid_: date, partition

**SWOB file**:
One hourly Surface Weather OBservation, an XML file whose name embeds the day,
hour, and station (e.g. `2026-07-10-0000-nb-dnred-anfi-anfi-AUTO-swob.xml`). Up
to 24 exist per station per day, one per hour. The filename is treated as an
opaque key; day and station come from the path, never from parsing the name.
_Avoid_: observation, report, record, XML

### Sync domain

**Run**:
A single invocation of the program, identified by a UTC timestamp (`runts`). A
run's log, manifest, and stdout summary all share that one `runts` as a
correlation key.
_Avoid_: execution, job, sync (as a noun)

**Window**:
The set of days a run processes. By default a rolling lookback of `anchor …
anchor − N` (`--days-back`, UTC), where the anchor — the newest day — is
`--as-of` when given, else today. Supplying `--date` replaces the window with
exactly the given days. Days outside the window are never re-listed.
_Avoid_: range, period, lookback (alone)

**Delta**:
The SWOB files a run actually downloads: those absent from **sync state**, or
whose `(last-modified, size)` in the directory listing differs from state.
_Avoid_: diff, changes, updates

**Added / Changed**:
The two kinds of delta record. **Added** = a file path never before in sync
state. **Changed** = a path already in state whose `(last-modified, size)`
differs (an upstream correction). These are the `action` values in the manifest.
_Avoid_: new/modified, created/updated

**Sync state**:
The persisted per-partner record of every SWOB file ever downloaded (within
retention), keyed `day → station → file → {mtime, size}`. It is the sole source
of truth for what "already downloaded" means; a file is only recorded here after
a successful download. One flat JSON file per partner.
_Avoid_: cache index, database, ledger, history

**Manifest**:
The per-run list of delta records handed to the downstream ingestion program.
One JSONL file per run, always written (even when empty).
_Avoid_: output list, report, changelog

**Retention**:
How long sync state, manifests, and logs are kept. By default the horizon is
**discovered from the server** each run (back to the earliest day in the
**availability window**), floored at 30 days so a truncated index can never purge
recent state; `--retention-days N` overrides both the discovery and the floor.
Entries for days older than the horizon are purged each run. The retention clock
is always real-today, never moved by `--as-of`; cache files are never purged.
_Avoid_: TTL, expiry, cleanup window

**Availability window**:
The `[earliest … latest]` span of `YYYYMMDD` day directories the server currently
offers, discovered once per run from the root index. A sliding, two-sided window
that moves forward each day. It is the authority for both the **input gate**
(explicitly-named days outside it hard-fail; an incidental `--days-back` tail
below `earliest` is dropped with a warning) and the automatic **retention**
horizon. See ADR 0004.
_Avoid_: availability horizon (alone), retention window

**Hour coverage**:
How many of the 24 hourly SWOB files a station has for a given day (`n/24`),
reported per station. There is deliberately **no** day-level "complete"
verdict — stations appear over time and some never publish all 24 hours, so a
per-day percentage would be misleading.
_Avoid_: completeness, complete day, fully synced
