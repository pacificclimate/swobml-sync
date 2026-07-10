# 04 — Retry & failure/exit semantics

**What to build:** The program tolerates transient upstream problems and reports
permanent ones correctly to its caller (kestra). Transient failures — connection
errors, 429, and 5xx — are retried with backoff (a few attempts) before giving
up. A missing day or station directory (404) is treated as legitimately empty,
not an error. A SWOB file that still fails after retries is logged and left out
of both sync state and the manifest, so it is naturally retried on the next run,
while the rest of the run continues. Successful work is persisted first, then the
run exits non-zero if one or more files failed permanently, and zero otherwise
(including when there was nothing to do).

**Blocked by:** 02 — Walking skeleton: sync one day end-to-end.

**Status:** done

- [x] Connection errors, 429, and 5xx are retried with backoff (bounded attempts) before being treated as failures
- [x] A 404 on a day or station directory is treated as empty, not an error
- [x] A file failing after retries is logged, omitted from state and manifest, and does not abort the run
- [x] Successes are persisted (state + manifest) before the process exits
- [x] Exit code is non-zero when ≥1 file failed permanently, zero otherwise (including "nothing to do")
- [x] Tests cover retry-then-success, permanent failure (omitted + non-zero exit), and 404-as-empty
