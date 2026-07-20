# 11 — Availability discovery, input gate & dynamic retention

**What to build:** Teach the run what the server actually still has, and use it
two ways: (1) an **input gate** that refuses or trims requests for days outside
that window, and (2) a **dynamic retention horizon** so we stop remembering state
for files we can no longer retrieve. Both are driven by one cheap discovery
request per run.

The motivation: the availability horizon was a guess. The live root index
(`https://hpfx.collab.science.gc.ca/`) currently holds ~53 day directories
(earliest `20260527`), i.e. a **~52-day, sliding** window — not the hard-coded 65
in ticket 07 / ADR 0001. "There is zero reason to retain state about files we can
no longer retrieve", and equally no reason to silently attempt days that provably
don't exist. So discover the real window and act on it.

## Discovery

- Once per run, fetch the **root index** (a new `layout` helper for `BASE_URL +
  "/"`) via the existing `HttpClient.get_text`, and parse it with the existing
  `listing` module. The **availability window** is `[earliest … latest]` of the
  `YYYYMMDD` directory entries — a two-sided span (`listing.directories()` gives
  the dir names; keep only those parseable as `YYYYMMDD`).
- Add *Availability window* to CONTEXT.md: the `[earliest … latest]` day span the
  server currently offers, discovered per run; the authority for the input gate
  and the automatic retention horizon.

### Discovery-failure tiers (deliberate, see ADR 0004)

- **Tier 1 — abort the whole run, non-zero, before any sync work:** the root
  index fetch errors / returns non-200, **or** it parses but contains **zero**
  valid `YYYYMMDD` directories. Against a fixed, always-on server, a total
  discovery failure is alarming enough to stop rather than sync blindly.
- **Tier 2 — proceed with the sync + gate, but skip *automatic* purge this run:**
  a valid index that simply does **not include the current UTC day**. A missing
  "today" is legitimate very early in a UTC day (the dir may not exist yet) and
  must not kill a routine sync — but it is reason enough not to *trust the
  horizon for deletion*. (An explicit `--retention-days` still purges; the 30-day
  floor still backstops any purge that does run.)

## Input gate (after discovery, before listing any day)

Partition the resolved day set against the availability window. The dividing line
is **explicit vs. incidental**:

- **Explicitly-named day outside the window → HARD FAIL** (non-zero, before any
  listing/download). "Explicitly named" = every `--date` value, and the
  `--as-of` anchor itself. Applies to **both** edges: a day too old *or* a future
  day beyond `latest` fails, because neither can be delivered. Rationale: the user
  pointed at a specific day that is gone/absent; silently dropping it would hide
  that — "we can't magically make them come back."
- **Incidental `--days-back` tail below the floor → WARN + DROP, sync the rest.**
  Days the user never named, merely swept in by the lookback reaching past the
  earliest available day, are dropped from the day set (never listed) and named in
  a single warning. The lookback spilling one day past the edge is expected, not
  an error. (The tail only ever runs *older* than the anchor, so it can only cross
  the lower edge; the upper edge is only ever reached by explicitly-named days.)
- All requested days outside → the all-explicit case is already a hard fail; a
  pure-tail run that is entirely below the floor also hard-fails (nothing to do).
  No days outside → no warning, proceed silently.

**Dropped days must never be listed**, so ticket-04's retry/failure/exit
semantics never count a provably-gone day as a download failure — a well-formed
run must not be reported as failed for asking about expired data.

Worked examples (earliest `20260527`, latest `20260718`):

- `--date 20260101` → fail (named, too old).
- `--date 20261231` → fail (named, future/beyond latest).
- `--as-of 20260101 --days-back 3` → fail (anchor named & gone).
- `--as-of 20260528 --days-back 5` → warn, drop `20260523/24/25/26`, sync `27/28`.
- default window with a large `--days-back` reaching past `20260527` → warn, drop
  the ancient tail, sync the rest.

## Dynamic retention (modifies ticket 07 housekeeping)

The discovered horizon replaces the hard-coded 65 for **automatic** purge. State
purge and manifest/log purge stay **connected on one horizon** (as today).

- `effective_auto_days = max(discovered_days, MIN_AUTO_RETENTION_DAYS)` where
  `discovered_days = today − earliest_available_day` and `MIN_AUTO_RETENTION_DAYS
  = 30`. The `max(…, 30)` is a **clamp-up**: automatic purge may delete genuinely
  ancient state (> 30 days) but must **never** delete state newer than 30 days,
  however low discovery comes back. This is the primary defence against a
  truncated index that reports a too-recent "earliest".
- **`--retention-days N` explicitly set → overrides discovery entirely**: purge by
  `N`, bypassing both discovery and the 30-day floor (the user may deliberately go
  below 30), deterministic and offline-safe. Discovery is *not* required for purge
  in this case — but is still fetched for the input gate.
- **Retention anchor stays real-today** (unchanged from ticket 07). `--as-of` does
  not move the retention clock; a historic-anchored run of days older than the
  horizon will still have its just-written state purged at end of run — that is
  accepted and documented, not worked around. **Cache files are still never
  purged** (only state entries and manifest/log files are).
- **Fail-closed:** any doubt skips purge rather than over-purges (Tier 2 above; a
  skipped purge self-heals on the next healthy run, an over-purge silently
  re-downloads and re-manifests real data).

## Docs

- **New ADR `docs/adr/0004-discover-availability-from-server.md`**: record the
  decision to *discover* the availability horizon from the root index rather than
  hard-code it (reversing the 65-day guess in ADR 0001), that one discovered
  horizon drives **both** the input gate and retention, the `max(discovered, 30)`
  floor, the `--retention-days` override, and the fail-closed / two-tier abort
  behaviour. Include a **Consequences** section per the existing ADR style
  (extra request per run; run now aborts on total discovery failure; retention is
  no longer a fixed number).
- **CONTEXT.md**: rewrite *Retention* from "default 65" to "discovered from the
  server, floored at 30 days, overridable via `--retention-days`"; add the
  *Availability window* term.
- **README**: update the `--retention-days` row description (now an override of a
  discovered default, not a fixed 65).
- One-line touch-up to **ADR 0001**'s "65-day retention horizon" mention, pointing
  the reader at 0004.

**Blocked by:** 10 — Moveable `--as-of` anchor (so the gate can cover the
`--as-of` anchor and its tail); 07 — End-of-run housekeeping (this rewrites the
retention horizon).

**Status:** done

- [x] One root-index fetch per run yields the two-sided availability window `[earliest … latest]`, reusing `HttpClient` + `listing`
- [x] Tier 1: root-index fetch failure OR zero valid `YYYYMMDD` dirs aborts the run non-zero before any sync work
- [x] Tier 2: a valid index missing the current UTC day proceeds with sync + gate but skips automatic purge
- [x] Gate: any `--date` value or the `--as-of` anchor outside the window (too old or future) hard-fails before listing
- [x] Gate: incidental `--days-back` tail below the earliest available day is warned about, dropped, and never listed; the rest syncs
- [x] Dropped-by-gate days never reach the ticket-04 failure/exit path
- [x] Automatic purge uses `max(discovered_days, 30)`; explicit `--retention-days` overrides discovery and the floor
- [x] Retention anchor stays real-today; cache files remain unpurged
- [x] ADR 0004 written; CONTEXT.md *Retention* rewritten + *Availability window* added; README + ADR 0001 touch-ups done
- [x] Tests cover: window discovery parse, both failure tiers, hard-fail on named out-of-window (old and future) days, warn+drop of the tail, the `max(discovered,30)` clamp, and the `--retention-days` override

## Comments

Implemented via `/implement`. New `availability` module owns discovery
(`discover` → `Availability`, Tier-1 `DiscoveryError`) and the input gate
(`gate` → kept days, `GateError`); `layout.root_url()` names the root index.
`config.retention_days` is now `int | None` (absent ⇒ discover). `sync.run`
discovers once, gates the resolved day set, and routes purge through `_purge`
(explicit `--retention-days` → override; else `housekeeping.auto_retention_days`
clamped at 30; Tier-2 missing-today ⇒ skip). CLI maps both abort exceptions to
exit code 2 (`EXIT_PREFLIGHT`). 135 tests pass; mypy + black clean.
