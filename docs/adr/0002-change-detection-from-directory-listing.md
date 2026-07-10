# Change detection from the directory listing

We decide whether a SWOB file needs downloading by comparing the `(last-modified,
size)` pair shown in the server's Apache directory index against the value
recorded in sync state. A file is downloaded only when it is absent from state
or either value differs. We do **not** issue per-file conditional GETs
(`If-Modified-Since`/`If-None-Match`) or hash file contents.

The listing already carries last-modified and size for every file, so this
detects both new files and upstream corrections at the cost of one listing fetch
per station — with a body fetch only for genuine deltas. Conditional GET would
add a request per candidate file every run; hashing would require downloading or
trusting ETags we haven't verified the server sends.

## Consequences

- The `(mtime, size)` pair is the change key stored in sync state, which is why
  state is keyed `day → station → file → {mtime, size}`.
- If the server ever reported a stale last-modified after changing a file's
  bytes without changing its size, we would miss that correction. Judged
  acceptable given the source is a standard Apache index over regenerated files.
