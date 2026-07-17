# 10 — Moveable `--as-of` window anchor

**What to build:** A new `--as-of YYYYMMDD` option (env `SWOBML_AS_OF`) that sets
the **newest day** of the rolling window. Today the window is always anchored at
UTC "today" (`window_days(now, days_back)` in `sync.py` → `[today, today-1, …
today-days_back]`). `--as-of` replaces that anchor with an arbitrary day, so the
window becomes `[as_of, as_of-1, … as_of-days_back]` — a *moveable today*. This
lets an operator pull an N-day window as it stood at a historic point (e.g.
"re-pull the 3 days ending 2026-06-01"). `--days-back` keeps its exact meaning:
it still counts **backward** from the anchor.

This is the small, self-contained half of the historic-window feature. It ships
on the existing "list the requested days and see what the server has" behavior —
**no availability gating is added here** (that is ticket 11). An `--as-of` day
the server no longer has will simply list empty / 404 through the existing
ticket-04 failure path, exactly as an out-of-range day does today; ticket 11 is
what turns that into a fast, clear failure.

## Decisions already made (do not re-litigate)

- **Anchor = newest day.** `--as-of` is the most-recent day of the window, not
  the oldest; `--days-back` extends backward from it. It is literally a moveable
  substitute for "today", nothing more.
- **Name.** `--as-of` / `SWOBML_AS_OF`, chosen over `--anchor`/`--end-date`/
  `--until` because it reads unambiguously as a point-in-time anchor and cannot
  be misread as the far (oldest) edge.
- **Validation: format only.** Reuse the existing `_valid_day` argparse type
  that `--date` uses (`YYYYMMDD` parses as a real calendar day). No bounds
  checking here — "is this day still available upstream" is ticket 11's job, via
  server discovery, not a hard-coded bound.
- **Precedence:** CLI `--as-of` > `SWOBML_AS_OF` env > default (absent → today).
  Mirror the existing resolver plumbing in `config.py` (`_resolve_str` shape; add
  an `as_of: str | None` field to the frozen `Config`).
- **Interaction with `--date`:** `--date` already *replaces* the whole window and
  ignores `--days-back`; it therefore also makes `--as-of` meaningless. When both
  `--date` and `--as-of` are supplied, **ignore `--as-of` but log a WARNING at
  run start** stating it is ignored under `--date`. (This is deliberately louder
  than the silent `--days-back` override, because `--as-of` is a more specific,
  intentful request that the user will want to know was dropped.)

## Where it hooks

- `config.py`: add the `--as-of` argument (default `None`, `type=_valid_day`),
  the `SWOBML_AS_OF` env fallback, and an `as_of` field on `Config`.
- `sync.py`: in `run()`, the day set is `list(config.days) or window_days(now,
  config.days_back)`. Change the window branch to anchor on `config.as_of` when
  set — pass the parsed anchor date into `window_days` (or add an anchor
  parameter) instead of `now`'s date. `runts` and the retention anchor **stay on
  real `now`** — `--as-of` moves the *data* window, never the run's identity or
  the retention clock (see ticket 07 / ADR 0001; retention anchor is out of scope
  here).
- Emit the both-supplied warning where the day set is resolved, before any
  listing.

**Blocked by:** 03 — Rolling window & date semantics.

**Status:** todo

- [ ] `--as-of YYYYMMDD` (env `SWOBML_AS_OF`) sets the newest day of the window; `--days-back` counts backward from it
- [ ] With `--as-of` absent, behaviour is byte-for-byte the current "anchored at today" window
- [ ] `--as-of` is format-validated as a real `YYYYMMDD` day, reusing `--date`'s validator; no range check
- [ ] Precedence CLI > env > default; explicit `--as-of` beats `SWOBML_AS_OF`
- [ ] When `--date` is also given, `--as-of` is ignored and a WARNING is logged at run start
- [ ] `runts` and the retention purge anchor remain real-today, unaffected by `--as-of`
- [ ] README usage table gains an `--as-of` / `SWOBML_AS_OF` row; CONTEXT.md *Window* entry notes the anchor is `--as-of` when given, else today
- [ ] Tests cover: the anchored day set, `--days-back` counting back from the anchor, env fallback + precedence, and the `--date` + `--as-of` warn-and-ignore path
