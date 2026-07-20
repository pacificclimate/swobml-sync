# Flat JSON sync state, not SQLite

The sync state (what SWOB files have been downloaded) is stored as one flat
JSON file per partner (`{dir}/{partner}/.sync-state.json`), loaded whole at
startup and rewritten atomically (temp file + `os.replace`) at the end of a run.
We deliberately avoid SQLite: this data lands on NFS, where SQLite's file
locking is unreliable and prone to corruption. Per-partner files (rather than
one global file) mean concurrent runs for different partners never contend on
the same file, and the atomic rewrite means a killed run never leaves a torn
state file.

## Consequences

- The whole state map is held in memory and rewritten each run; fine at the
  expected scale (thousands of small entries, bounded by the retention horizon —
  now discovered from the server rather than a fixed 65 days, see
  [0004](0004-discover-availability-from-server.md); see
  [0002](0002-change-detection-from-directory-listing.md) for the per-file key).
- No concurrent-safe updates *within* a single partner; a partner is assumed to
  be synced by at most one run at a time.
