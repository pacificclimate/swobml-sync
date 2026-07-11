# swobml-sync — feature build

A Python CLI that syncs one swob-ml **partner**'s hourly observation files from
the ECCC HPFX server down to a local directory tree. It tracks what it has seen
in flat per-partner JSON **sync state**, so a re-run picks up files that were
previously unavailable or corrected upstream, and emits a per-run **manifest**
of added/changed files for a downstream ingestion program. Discovery walks the
server's Apache directory index; change detection compares the listing's
`(last-modified, size)` against state.

This folder is the tracker for that build. The tickets below are the living
spec — each is a tracer-bullet vertical slice with acceptance criteria. For the
shared vocabulary see [`CONTEXT.md`](../../CONTEXT.md); for the decisions with
lasting consequences see [`docs/adr/`](../../docs/adr/).

## Tickets (dependency order)

| # | Ticket | Blocked by | Status |
|---|--------|-----------|--------|
| 01 | [Scaffold & CLI surface](issues/01-scaffold-and-cli.md) | — | done |
| 02 | [Walking skeleton: sync one day](issues/02-walking-skeleton-one-day.md) | 01 | done |
| 03 | [Rolling window & date semantics](issues/03-rolling-window-and-date-semantics.md) | 02 | done |
| 04 | [Retry & failure/exit semantics](issues/04-retry-and-failure-exit-semantics.md) | 02 | done |
| 05 | [Concurrency](issues/05-concurrency.md) | 03, 04 | done |
| 06 | [Persistent file logging](issues/06-persistent-file-logging.md) | 02 | done |
| 07 | [End-of-run housekeeping](issues/07-end-of-run-housekeeping.md) | 03, 06 | done |
| 08 | [Dockerfile](issues/08-dockerfile.md) | 01 | ready-for-agent |
| 09 | [Dual-registry CI](issues/09-dual-registry-ci.md) | 08 | ready-for-agent |

```
01 ─┬─ 02 ─┬─ 03 ─┬─ 05
    │      ├─ 04 ─┘
    │      └─ 06 ── 07
    │         03 ─┘
    └─ 08 ── 09
```

**Frontier:** 05 is done; 06 and 08 are startable now (07 unblocks once 06 lands).

Work one ticket at a time with `/implement`, clearing context between tickets.
