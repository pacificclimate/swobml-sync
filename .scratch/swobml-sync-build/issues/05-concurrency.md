# 05 — Concurrency

**What to build:** Discovery and download run concurrently through a bounded
thread pool sized by `--workers` (default 8), sharing a single HTTP session
whose connection pool is sized to the worker count. The run is phased — list
stations concurrently, list each station's files concurrently to compute the
delta, then download the delta concurrently — all through the same pool. The
retry and failure/exit semantics from ticket 04 are preserved under
concurrency, and the outputs (files on disk, sync state, manifest, summary) are
identical to a serial run.

**Blocked by:** 03 — Rolling window & date semantics; 04 — Retry & failure/exit
semantics.

**Status:** done

- [x] Station listing, file listing, and downloads run through one bounded pool sized by `--workers` (default 8)
- [x] A single shared HTTP session is used, its connection pool sized to the worker count
- [x] Retry, 404-as-empty, permanent-failure-skip, and non-zero-exit semantics still hold under concurrency
- [x] Outputs are identical to a serial run over the same source
- [x] Sync-state and manifest writes remain safe with concurrent downloads feeding them
