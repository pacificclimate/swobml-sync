# 03 — Rolling window & date semantics

**What to build:** A run without `--date` syncs a rolling **window** of days —
today plus the previous `--days-back` days (default 2), all computed in UTC — by
applying the single-day sync from ticket 02 to each day in the window. Supplying
one or more `--date` values instead syncs exactly those days and ignores
`--days-back`. The manifest, sync state, and stdout summary span all processed
days, and `days` in the summary lists them.

Because a run only merges the days it processed into the loaded sync state and
never rewrites untouched days, a short default run and a later `--date` backfill
of an old day coexist without clobbering each other.

**Blocked by:** 02 — Walking skeleton: sync one day end-to-end.

**Status:** done

- [x] With no `--date`, the run processes today and the previous `--days-back` days, all in UTC
- [x] Any `--date` given replaces the window: exactly those days are processed and `--days-back` is ignored
- [x] Sync state merges only the processed days; days outside the window remain untouched in state
- [x] Manifest and stdout summary aggregate across all processed days; `days` lists them
- [x] Tests cover the rolling-window day set, the `--date` override, and non-clobbering of untouched days
