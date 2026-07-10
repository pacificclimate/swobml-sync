# Allow requests and lxml despite the standard-library preference

`notes.md` states a preference for standard libraries "where possible," which
would point at `urllib.request` + `html.parser`. We nonetheless take two
third-party runtime dependencies: **requests** (HTTP sessions, connection
pooling, and urllib3 `Retry` for backoff on 5xx/429/connection errors) and
**lxml** (robust parsing of the Apache index HTML). The ergonomics — retry
policy, pooled concurrency across the thread pool, and forgiving HTML parsing —
are worth substantially more than the ~50 lines of hand-rolled helpers the
stdlib-only path would require, and both ship manylinux wheels so the
`python:3.12-slim` image stays simple.

This is recorded so a future reader does not "fix" the code back to stdlib
assuming the dependencies were accidental — they are a deliberate deviation from
the stated preference.

## Consequences

- Two dependencies to track for security updates.
- Runtime deps are limited to these two; anything beyond them should be
  reconsidered against the original stdlib preference.
