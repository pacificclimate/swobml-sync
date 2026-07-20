# Discover the availability window from the server

We **discover** the availability window from the server's root index each run
rather than hard-coding it. This reverses the fixed "65-day retention horizon"
guess of [0001](0001-flat-json-sync-state-on-nfs.md): the live root index
(`https://hpfx.collab.science.gc.ca/`) holds only the day directories the server
currently offers — a sliding, two-sided window (recently ~52 days, earliest
`20260527`) that moves forward each day. One cheap discovery request per run
reads that index and takes its `[earliest … latest]` `YYYYMMDD` span as the
authority for two things at once:

- **An input gate.** A day the user *explicitly named* — every `--date` value and
  the `--as-of` anchor — that falls outside the window is a hard failure before
  any listing, at **either** edge (too old, or a future day beyond `latest`):
  neither can be delivered, and silently dropping a day the user pointed at would
  hide that it is gone. A day merely swept in by a long `--days-back` tail
  reaching past `earliest` is instead dropped with one warning while the rest
  syncs — the lookback spilling one day past the edge is expected, not an error.
  Dropped days are never listed, so the ticket-04 failure/exit path never counts a
  provably-gone day as a download failure.
- **Automatic retention.** The discovered horizon (`today − earliest`) replaces
  the fixed 65 for automatic purge, clamped up to a **30-day floor**
  (`max(discovered, 30)`) so a truncated index reporting a too-recent "earliest"
  can never delete state newer than 30 days. An explicit `--retention-days N`
  overrides discovery *and* the floor (the user may deliberately go below 30),
  keeping purge deterministic and offline-safe.

Discovery is deliberately **fail-closed** with two tiers:

- **Tier 1 — abort the whole run, non-zero, before any sync work:** the root
  index fails to fetch (any error, including a non-200) or parses but contains
  **zero** valid `YYYYMMDD` directories. Against a fixed, always-on server a total
  discovery failure is alarming enough to stop rather than sync blindly.
- **Tier 2 — sync and gate as normal, but skip *automatic* purge this run:** a
  valid index that simply lacks the current UTC day. A missing "today" is
  legitimate very early in a UTC day (the directory may not exist yet) and must
  not kill a routine sync, but it casts enough doubt on the discovered "earliest"
  that we do not trust it for deletion. An explicit `--retention-days` still
  purges; the 30-day floor still backstops any automatic purge that does run.

The retention *anchor* stays real-today: `--as-of` moves the data window, never
the retention clock, and cache files are never purged (only state entries and
manifest/log files).

## Consequences

- Every run makes one extra request (the root index) before any sync work.
- A run now **aborts** on a total discovery failure (Tier 1) where before it would
  have listed each requested day and let absent days 404 through as empty. This is
  the intended trade: a fast, clear stop over a blind sync.
- Retention is no longer a fixed number. Automatic purge tracks the sliding
  window (clamped at 30 days); only an explicit `--retention-days` is constant and
  offline-safe. A historic `--as-of` run of days older than the horizon will still
  have its just-written state purged at end of run — accepted and documented, not
  worked around (the cache files themselves remain).
