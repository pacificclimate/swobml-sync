# 09 — Dual-registry CI publishing

**What to build:** A GitHub Actions workflow that builds the image and publishes
it to both GitHub Container Registry (ghcr.io, authenticated with the built-in
`GITHUB_TOKEN`) and Docker Hub (under the `pacificclimate` org as
`pcic/swobml-sync`, authenticated with repository secrets). It mirrors the team's
existing convention (the `pacificclimate/climate-explorer-backend`
`docker-publish.yml`): build on every branch push and on bare semver tags
(`X.Y.Z`), derive tags once with `docker/metadata-action`, push both registries
in one `docker/build-push-action` step, and tag `:latest` on the default branch.

**Blocked by:** 08 — Dockerfile.

**Status:** done

- [x] Workflow logs into both ghcr (via `GITHUB_TOKEN`) and Docker Hub (via secrets) and pushes to both
- [x] Docker Hub images publish under `pcic/swobml-sync`
- [x] Triggers on branch pushes (image tag = branch name) and bare semver tags `X.Y.Z`
- [x] `:latest` is applied only on the default branch (via metadata-action `is_default_branch`)
- [x] Tags are derived with `docker/metadata-action` and pushed via a single `docker/build-push-action` step
