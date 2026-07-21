# Persist run stats as a per-run file for a separate dashboard

Each run counts the web requests it makes and records them two ways: on the
stdout summary and as a durable per-run **stats file**, so a later dashboard tool
has something on disk to aggregate across partners. Two counters are kept —
`listing_requests` (every directory-index fetch: availability discovery plus each
day and station index) and `downloads` (every SWOB file fetch); their sum is the
total web requests, derived on demand and never stored. Two decisions have
lasting consequences.

## Count logical requests, not round-trips

We count one request per `HttpClient` call, not per HTTP round-trip. The retries
urllib3 makes inside a single call (see
[0003](0003-allow-requests-and-lxml.md)) stay invisible: a listing retried twice
before succeeding is one `listing_request`. Every call counts regardless of
outcome, including a `404`/`NotFound` and a permanent failure after retries — a
request was still issued.

This keeps counting **simple and testable**: it lives in one small
`CountingClient` decorator that wraps any `HttpClient` and forwards
`get_text`/`download`, tallying the matching counter (thread-safely — the phases
fan those calls out across a bounded pool). `run()` wraps whatever client it is
handed, real or the test fake, so counting covers every run without a caller
opting in, and neither the sync phases nor `RequestsClient` are touched. Retries
are a transport concern that belongs below this seam, not a number the dashboard
should see: what a run "cost" is the logical work it asked for, not how flaky the
transport was on the day.

## Persist per-run files a separate tool aggregates

Each run writes its whole record to `<dir>/<partner>/stats/<runts>.json`, beside
the manifest and keyed by the same `runts`. The record is a superset of the
stdout line: `runts`, `added`, `changed`, `failed`, `days`, `coverage`,
`listing_requests`, `downloads`. One serialization path feeds both the stdout
line and the file, so the two can never drift.

We deliberately do **not** fold stats into the manifest, which stays
delta-records-only — its contract with the downstream ingestion program is "the
files this run added or changed", and stats are neither. Nor do we rely on the
orchestrator (kestra) to capture the stdout line: a per-run file on the shared
tree is durable, survives a lost or rotated log, and is trivially aggregated by a
**separate** `swobml-dashboard` tool (tickets 13–14) that never has to run the
sync or parse its logs. Per-run files also age out for free: `purge_run_files`
sweeps `stats/` on the same runts horizon as manifests and logs, so a stats file
lives exactly as long as the manifest it describes.

## Consequences

- One extra small write per run (the stats file). It is written atomically, like
  every other file in the tree, so a killed run never leaves a torn record.
- The `stats/` directory joins `manifests/` and `logs/` under retention with no
  new knob: foreign files (stems that don't parse as a `runts`) are left alone,
  and the current run's own `stats/<runts>.json` carries today's runts and so is
  never in purge scope.
- The counts measure logical requests, so they will **understate** actual HTTP
  round-trips whenever retries fire. This is intended — the dashboard reports the
  work a run asked for, and a spike in transport retries is a transport-layer
  concern surfaced by logs, not by this number.
- A new field added to the run record surfaces in both the stdout line and the
  persisted file at once, because one function serializes both; the dashboard can
  rely on the two staying in lockstep.
