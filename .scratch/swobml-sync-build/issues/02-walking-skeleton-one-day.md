# 02 — Walking skeleton: sync one day end-to-end

**What to build:** For a single partner and a single day (given via `--date`),
the program performs a complete sync: it discovers every station for that day
from the server's directory listing, determines which SWOB files are new or
changed, downloads exactly those, records them, and reports what it did. Run
twice against an unchanged source, the second run downloads nothing and reports
an empty delta.

Concretely, one run:
- discovers the day's stations and their SWOB files by parsing the Apache
  directory index (lxml),
- computes the **delta** — files absent from **sync state**, or whose
  `(last-modified, size)` differs from what state records
  (see [ADR 0002](../../../docs/adr/0002-change-detection-from-directory-listing.md)),
- downloads each delta file to the local cache tree under the day and station,
  writing via a temp file so a killed run leaves no half-written SWOB file,
- updates the per-partner flat JSON **sync state**, rewritten atomically, only
  recording files that downloaded successfully
  (see [ADR 0001](../../../docs/adr/0001-flat-json-sync-state-on-nfs.md)),
- writes a timestamped JSONL **manifest** of the run's delta records (each with
  path relative to `dir`, `action` of added or changed, station, day,
  last-modified, size), always written even when empty,
- prints a one-line JSON summary to stdout and logs progress to stderr.

This ticket also stands up the **test harness**: saved real directory-index HTML
fixtures and a mocked HTTP layer, so the discovery → delta → state → manifest
logic is tested without touching the network.

Serial only — no rolling window, retries, concurrency, retention, or file
logging yet.

**Blocked by:** 01 — Scaffold & CLI surface.

**Status:** done

- [x] `swobml-sync <partner> <dir> --date <YYYYMMDD>` downloads that day's new/changed SWOB files into `cache/{day}/{station}/{file}` under the partner
- [x] Delta is computed from listing `(last-modified, size)` versus per-partner JSON sync state; unchanged files are skipped
- [x] Sync state is a per-partner flat JSON file, keyed day → station → file → {mtime, size}, rewritten atomically, recording only successful downloads
- [x] A timestamped JSONL manifest with rich records is always written (empty file when nothing changed)
- [x] stdout is a single JSON summary line `{manifest, added, changed, failed, days}`; diagnostics go to stderr
- [x] A second run with no upstream change downloads nothing and reports an empty delta
- [x] Downloads are atomic (temp file + rename); an interrupted run leaves no truncated file recorded as done
- [x] Tests cover parse → delta → state-merge → manifest against saved index-HTML fixtures with mocked HTTP
