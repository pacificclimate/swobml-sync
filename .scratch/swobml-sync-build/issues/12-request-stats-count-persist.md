# 12 — Request stats: count, surface & persist per run

**What to build:** Teach a run to count the web requests it makes and report
them two ways — on the stdout summary and as a durable per-run stats file — so a
later dashboard tool (tickets 13–14) has something on disk to aggregate. Two new
counters: **`listing_requests`** (every directory-index fetch: availability
discovery + each day index + each station index) and **`downloads`** (every SWOB
file fetch). Total web requests is their sum, derived, never stored.

## Counting

- Count **logical** requests — one per `HttpClient` call — not HTTP round-trips.
  Retries live inside urllib3 and stay invisible; a listing retried twice before
  succeeding is one `listing_request`. Every call counts regardless of outcome,
  including a `404`/`NotFound` and a permanent failure — a request was still
  issued.
- Do it with a small **`CountingClient` decorator** that wraps an `HttpClient`
  and forwards `get_text`/`download`, incrementing the matching counter on each
  call. It is the one place counting lives, so the sync phases and
  `RequestsClient` are untouched.
- **Thread-safe:** the phases fan out across one bounded pool, so `get_text`/
  `download` are called concurrently — increments must be guarded (a lock).
- **`run()` wraps whatever client it is handed** (real or the test fake) in the
  `CountingClient` internally, then reads the two totals into `RunResult` at the
  end. So counting covers every run, tests included, and no caller has to opt in.

## Surfacing & persistence

- Add `listing_requests` and `downloads` to `RunResult` and to the **stdout JSON
  summary** alongside `added`/`changed`/`failed`/`coverage`.
- Persist the whole run record to **`<dir>/<partner>/stats/<runts>.json`**,
  written next to the manifest at end of run. Its contents are a **superset of
  the stdout line**: `runts`, `added`, `changed`, `failed`, `days`, `coverage`,
  `listing_requests`, `downloads`. One serialization path feeds both (the stdout
  line is the same record minus nothing it needs).

## Retention

- Extend **`housekeeping.purge_run_files`** to also sweep the `stats/` directory,
  so per-run stats files age out on the **same runts horizon** as manifests and
  logs. Foreign files (stems that don't parse as a `runts`) are left alone, as
  today. The current run's own `stats/<runts>.json` carries today's runts and so
  is never in purge scope.
- No new retention knob and no change to how the horizon is chosen — stats simply
  join the existing per-run-file purge.

## Docs

- **New ADR `docs/adr/0005-persist-run-stats-for-a-separate-dashboard.md`**:
  record (a) counting **logical** requests, not round-trips, and why (simplicity,
  testability, retries are a transport concern); (b) persisting each run's stats
  as a **per-run file** a **separate tool** later aggregates, rather than folding
  them into the manifest (which stays delta-records-only) or relying on the
  orchestrator to capture stdout. Include a **Consequences** section per the
  existing ADR style.
- **CONTEXT.md**: add a *Run stats* term — the per-run record of request counts
  and outcome, emitted on stdout and persisted as one file per run under
  `stats/`, on the same retention horizon as manifests/logs.
- **README**: document the two new stdout fields and the `stats/` output
  directory in the Output section.

**Blocked by:** None — can start immediately. (Builds on the finished sync tool:
the `HttpClient` seam from ticket 05 and the per-run-file purge from ticket 07.)

**Status:** ready-for-agent

- [ ] `CountingClient` wraps an `HttpClient` and counts `get_text` as `listing_requests` and `download` as `downloads`, thread-safely, once per logical call (including 404s and failures)
- [ ] `run()` wraps whatever client it is given so the counts cover real and fake clients alike, and reads the totals into `RunResult`
- [ ] `listing_requests` and `downloads` appear on the stdout JSON summary
- [ ] Each run writes `<dir>/<partner>/stats/<runts>.json` as a superset of the stdout line
- [ ] `purge_run_files` sweeps `stats/` on the same runts horizon as manifests/logs; foreign files and the current run's file are never removed
- [ ] ADR 0005 written; CONTEXT.md *Run stats* term added; README Output section updated
- [ ] Tests cover: counting across the three listing sites + downloads, 404/failure still counted, thread-safe totals under concurrency, the persisted file's shape, and stats-file purge on the horizon
