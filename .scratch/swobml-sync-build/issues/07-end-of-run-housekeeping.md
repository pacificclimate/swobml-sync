# 07 — End-of-run housekeeping: hour coverage & retention purge

**What to build:** Two things that happen at the end of every run, over the same
partner tree.

**Hour coverage reporting.** For each processed day, report each station's
**hour coverage** — how many of the 24 hourly SWOB files it has (`n/24`). Per
`CONTEXT.md` there is deliberately no day-level "complete" verdict; coverage is
per station. Per-station coverage goes to the log, and an aggregate goes into the
stdout JSON summary.

**Retention purge.** At the end of the run, purge anything older than
`--retention-days` (default 65, matching the upstream ~65-day availability
horizon): sync-state entries for expired days, and manifest and log files whose
timestamp is older than the horizon. Purge is by calendar day relative to the
run date and is independent of the `--days-back` window (short fetch window, long
memory).

**Blocked by:** 03 — Rolling window & date semantics; 06 — Persistent file
logging.

**Status:** ready-for-agent

- [ ] Per-station hour coverage (`n/24`) is reported per processed day in the log
- [ ] An aggregate coverage figure appears in the stdout JSON summary; no day-level completeness verdict is emitted
- [ ] Sync-state entries for days older than `--retention-days` are purged at end of run
- [ ] Manifest and log files older than the retention horizon are purged
- [ ] Purge is by calendar day relative to run date and independent of `--days-back`
- [ ] Tests cover coverage counting and purge of state, manifests, and logs past the horizon
