# 08 — Dockerfile

**What to build:** A Docker image from which the CLI runs. Based on
`python:3.12-slim`, it installs the package and its two runtime dependencies and
sets the entry point to `swobml-sync`, so `docker run <image> <partner> <dir>
...` behaves exactly like the local CLI. The image stays slim — the runtime
dependencies ship manylinux wheels, so no build toolchain is needed.

**Blocked by:** 01 — Scaffold & CLI surface.

**Status:** ready-for-agent

- [ ] Image builds from `python:3.12-slim` and installs the package with runtime deps
- [ ] Entry point invokes `swobml-sync`; args pass straight through to the CLI
- [ ] `docker run` with valid args behaves identically to the local CLI (verified with a mocked or real single-day run)
- [ ] Image contains no build toolchain beyond what the slim base provides
