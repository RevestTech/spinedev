# `.github/` — GitHub Actions CI/CD for Spine v1.0

Drafted per `docs/V1_SHIP_CHECKLIST.md` §1 (Vendor-side build pipeline).

This directory contains five workflows under `workflows/`:

| File | Triggers | Purpose |
| ---- | -------- | ------- |
| `ci.yml`            | `pull_request` (any branch) + `push` to `main` | lint + tests + smoke + SPA build per `make lint` |
| `docker-build.yml`  | `push` to `main`, tag `v*.*.*`, PR (build-only)| multi-arch `hub`/`vault`/`keycloak` build + cosign + Trivy |
| `flyway-gate.yml`   | PR touching `db/flyway/sql/**`                 | fresh-DB migrate + validate + smoke |
| `release.yml`       | tag `v*.*.*`                                   | release tarball + cosign + GitHub Release |
| `nightly.yml`       | cron `0 6 * * *` UTC + manual dispatch         | DR drill, BYOC dry-runs (6 clouds), Shamir round-trip, 12 h smoke |

All workflows pin actions by major-version tag (e.g. `@v4`) and avoid `@latest`.

## Required GitHub Secrets

Configure under **Settings → Secrets and variables → Actions → Repository
secrets** (or environment-scoped if you adopt deployment environments).

| Name | Used by | Purpose |
| ---- | ------- | ------- |
| `GITHUB_TOKEN` *(auto)* | `docker-build.yml`, `release.yml` | push to GHCR + create Release. Auto-injected; just confirm `packages: write` is enabled for the workflow. |
| `COSIGN_PRIVATE_KEY`    | `docker-build.yml`, `release.yml` | cosign signing key. Generate with `cosign generate-key-pair`; keep the public key checked into `docs/security/cosign.pub` so customers can verify. **This is the CI build-signing identity, NOT the Shamir-split license key from §2a.** |
| `COSIGN_PASSWORD`       | `docker-build.yml`, `release.yml` | passphrase for the key above. |
| `STATUS_REGISTRY_URL`   | `nightly.yml`                     | POST endpoint for vendor heartbeat (#31 layer 5). Optional — heartbeat step skips when unset. |
| `STATUS_REGISTRY_TOKEN` | `nightly.yml`                     | Bearer token for the above. |

The Shamir license-signing key shares (per
`docs/V1_SHIP_CHECKLIST.md` §2a) are **never** stored in GitHub Secrets — they
live offline with the 5 custodians and are reconstructed in vendor
infrastructure for license issuance, not in CI.

## Required GitHub Settings to enable

1. **Settings → Actions → General → Workflow permissions:** set to
   *"Read and write permissions"*. The workflows narrow this per-job, but the
   defaults need to allow `packages: write` / `contents: write`.
2. **Settings → Actions → General → Fork pull request workflows:** keep at
   *"Require approval for first-time contributors"* (default).
3. **Settings → Packages → Inherit access from source repository:** enable so
   pushed images on GHCR are reachable for customers who buy a license.
4. **Settings → Branches → Branch protection rule for `main`:**
   - **Require a pull request before merging** (1 approval).
   - **Require status checks to pass before merging** — select:
     - `ci / lint-py (ruff)`
     - `ci / lint-shell (shellcheck)`
     - `ci / lint-sql (sqlfluff)`
     - `ci / lint-md (markdownlint)`
     - `ci / lint-spa (svelte-check)`
     - `ci / pytest-py (3.11)`
     - `ci / pytest-py (3.12)`
     - `ci / smoke-test (tools/smoke-test.sh)`
     - `ci / spa-build (vite)`
     - `flyway-gate / flyway migrate + validate (fresh pgvector pg16)`
       *(required only when `db/flyway/sql/**` changed)*
   - **Require branches to be up to date before merging:** on.
   - **Require signed commits:** on (matches `git tag -s` policy at launch).
   - **Include administrators:** on (no human bypass; matches the AI-driven
     posture).
5. **Settings → Tags → Tag protection:** protect `v*` so only repo
   maintainers can cut releases.

## Caching strategy

| Cache | Where | Action |
| ----- | ----- | ------ |
| pip wheels        | every Python job | `actions/setup-python@v5` `cache: pip` |
| npm modules       | `lint-spa`, `spa-build` | `actions/setup-node@v4` `cache: npm` on `shared/ui/spa/package.json` |
| Docker buildx layers | `docker-build.yml` | `cache-from`/`cache-to` `type=gha,scope=spine-<image>,mode=max` |
| sqlfluff config   | (implicit via pip cache) | sqlfluff binary pulled from pip cache |

We deliberately avoid caching across forks for security (default GHA behavior).

## Validation performed

All five YAML files were syntax-checked with `yaml.safe_load`:

```bash
python3 -c "import yaml, sys; [yaml.safe_load(open(f)) for f in sys.argv[1:]]" \
  .github/workflows/ci.yml \
  .github/workflows/docker-build.yml \
  .github/workflows/flyway-gate.yml \
  .github/workflows/release.yml \
  .github/workflows/nightly.yml
```

## Independent decisions

- **GHCR over Docker Hub.** Auth via `GITHUB_TOKEN` (zero secret rotation),
  no anonymous pull rate limits, and signing flow matches Sigstore docs.
- **SLSA L2, not L3.** L2 (build provenance attestation + signed images via a
  hosted CI) is achievable today with `actions/attest-build-provenance@v2` +
  buildx `provenance: true`. L3 requires hermetic builders + isolated signing
  keys; deferred to v1.1+ once a hardened builder farm is in scope.
- **Trivy over Grype** for image scanning — single binary, fast, blocks on
  HIGH/CRITICAL only (MEDIUM ignored to avoid flapping on upstream churn).
- **Service-container Postgres over Testcontainers** — keeps the CI step
  declarative (`services:`), no Docker-in-Docker, and matches what
  `tools/smoke-test.sh` expects on `POSTGRES_HOST_PORT=33000`.
- **Re-run lint inside `release.yml`** instead of relying on cross-workflow
  `needs:` (which GHA does not support). A tag-push that bypasses PR review
  still cannot ship a release that failed lint.
- **`pytest-py` matrix on 3.11 + 3.12.** The repo pins `python:3.11-slim` in
  `hub/Dockerfile`; 3.12 is the next-stop forward-compat check so we catch
  break-on-upgrade early.
- **`smoke-12h`** runs only nightly (not per-PR) — 12 h wall-clock would
  obliterate PR throughput.

## v1.1+ follow-ups

- **GitLab CI mirror** (~75% of customers per #14 enterprise tier may need
  to host the build internally). Pattern: copy `.gitlab-ci.yml` from
  `ci.yml` job-for-job; replace `services:` with the GitLab `services:` block
  syntax (already very similar).
- **Real `publish-helm-chart` impl** — currently a stub in `release.yml`.
  Path: `helm package charts/spine` → `helm push oci://ghcr.io/.../charts` →
  `cosign sign oci://...`.
- **OpenAPI snapshot drift gate** — per checklist §1
  (`shared/ui/spa/scripts/openapi-sample.json` matches live spec). Add a
  job to `ci.yml` once the snapshot harness is wired.
- **SBOM publication** — `docker buildx build --sbom=true` produces an SBOM
  attestation today; v1.1 should also push it to a vendor SBOM registry
  (e.g. `dependency-track`).
- **SLSA L3 hardening** — migrate `cosign sign` from keyed (`--key`) to
  keyless OIDC (`--identity-token`), and move builds to a Reusable Workflow
  in a dedicated `spine-build` repo with restricted permissions.
- **Per-cloud live BYOC integration tests** — currently `--dry-run` only.
  Live runs need per-cloud test accounts + budget caps + teardown guards.
- **Branch-protection-as-code** — manage rules via a Terraform/GH Apps
  workflow rather than the UI, so the protection set is version-controlled.
