# 01 — Scaffold & CLI surface

**What to build:** An installable command-line program `swobml-sync` that a user
can run to see its full argument surface, even though it performs no sync yet.
Running `swobml-sync --help` lists every flag; running it with valid arguments
parses and validates them (and reports clear errors on bad input); every flag
can alternatively be supplied via a `SWOBML_*` environment variable, with an
explicit command-line argument winning over the env var when both are present.

Establishes the repository itself: a git repository, a Python package, and the
dependency set (requests + lxml at runtime, pytest for development). See
[ADR 0003](../../../docs/adr/0003-allow-requests-and-lxml.md) for why those two
runtime dependencies are allowed.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] Repository is a git repository with a Python package and console entry point named `swobml-sync`
- [ ] `partner` and `dir` are required; `--days-back` (default 2), `--date` (repeatable), `--retention-days` (default 65), `--workers` (default 8), `--manifest`, `--log-level` (default INFO) are all present
- [ ] Every flag has a `SWOBML_*` environment-variable fallback; a command-line argument overrides the env var when both are set
- [ ] Invalid input (e.g. a malformed `--date`, a non-integer `--workers`) exits non-zero with a readable message
- [ ] `--help` documents all flags; a test asserts argument parsing and env-var precedence
