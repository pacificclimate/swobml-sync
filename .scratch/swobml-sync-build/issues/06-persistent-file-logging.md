# 06 — Persistent file logging

**What to build:** In addition to the stderr stream, each run writes a persistent
log file under the partner's `logs` directory, named with the run's timestamp so
it shares one correlation key with that run's manifest and stdout summary — a red
run can be traced from its summary straight to its exact log. Both the stderr
stream and the file receive the same records at the configured `--log-level`.

**Blocked by:** 02 — Walking skeleton: sync one day end-to-end.

**Status:** ready-for-agent

- [ ] Each run writes `logs/{runts}.log` under the partner, using the same `runts` as that run's manifest
- [ ] stderr and the file log receive the same records, both honouring `--log-level`
- [ ] The correlation key ties together the log, the manifest, and the stdout summary for one run
- [ ] A test asserts the log file is created with the run's timestamp and shares the manifest's key
