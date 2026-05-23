# Spine v1.0 — Ship Checklist

> **Status:** Canonical pre-launch checklist. The v3 build is **CODE COMPLETE** (57 commits since `1da7148`).
> All remaining gates are **operational / external / install-time** — nothing here requires more agent code.
>
> **Source of truth.** This doc is the single launch gate for **customer ship**.
> For **product vision and wiring priorities**, read
> [`docs/SPINE_MASTER.md`](SPINE_MASTER.md) first. If this doc conflicts with
> SPINE_MASTER on *what to build*, SPINE_MASTER wins. If anything conflicts on
> *launch ops*, this doc wins.
>
> **Owner:** Khash (solo human per #21). AI agents may execute items where flagged
> *(AI-drivable)* — but launch sign-off is human-only.

---

## 0. Pre-ship sanity check (run this first)

- [ ] `git log --oneline 1da7148..HEAD` — confirm 57+ commits land cleanly on `main`
- [ ] `bash tools/smoke-test.sh` — must show **99 PASS / 0 FAIL / 1 WARN / 0 SKIP**
- [ ] Read all 5 canonical docs end-to-end as a returning user would:
  - `README.md` → `docs/positioning.md` → `docs/PRD.md` → `docs/ARCHITECTURE.md` → `INSTALL.md`
  - Then operational guides: `HUB_OPERATIONS_GUIDE` / `DEPLOYMENT_SHAPES` / `SECURITY_GUIDE` / `LICENSING_GUIDE` / `FEDERATION_GUIDE` / `DR_RUNBOOK`
- [ ] Spot-check 3 random subsystems' READMEs (any of: `hub/`, `vault/`, `keycloak/`, `federation/`, `license/`, `evidence/`, `learning/`, `recovery/`, `migration/`, `shared/integrations/`)
- [ ] Confirm `docs/V3_DESIGN_DECISIONS.md` 34 decisions match what shipped

## 1. Vendor-side build pipeline (CI/CD)

- [ ] **Multi-arch Docker images** for `hub/`, `vault/`, `keycloak/` published to vendor artifact registry
  - `docker buildx build --platform linux/amd64,linux/arm64`
  - Signed with Sigstore (`cosign sign`)
  - Provenance attestation (SLSA L2 minimum)
- [ ] **SPA build pipeline** — `cd shared/ui/spa && npm ci && npm run build` produces `dist/` consumed by `hub/Dockerfile` second stage
- [ ] **Flyway migration gate** — V1-V36 applies clean on fresh Postgres in CI; rollback drill verified
- [ ] **Smoke test in CI** — `bash tools/smoke-test.sh` on every PR; failing PR cannot merge
- [ ] **pyshamir** pinned in `requirements.txt` (and CI Docker layer) — auto-activates 26 Shamir tests
- [ ] **shellcheck / ruff / sqlfluff / markdownlint** all clean — `make lint` passes
- [ ] **`make hygiene`** sweeps clean — no stale workspace state in repo
- [x] **OpenAPI snapshot drift gate** — `tools/openapi-drift-gate.py` builds the live spec via `build_openapi(create_app())` and verifies every path/method/component-schema referenced by `shared/ui/spa/scripts/openapi-sample.json` still exists in live. Wired into CI (`.github/workflows/ci.yml`). Refresh snapshot via `--print-live-only > shared/ui/spa/scripts/openapi-sample.json`. Last run 2026-05-18: clean.

## 2. Vendor-side production setup

### 2a. Vendor vault + signing key

- [ ] Production **vendor vault** (OpenBao / Vault Enterprise) deployed in vendor's own infrastructure (3-region replication; Shamir 3-of-5 unseal)
- [ ] **License signing key** generated via `tools/license-sign.sh shamir-split --out <tmpfs-dir>`
- [ ] Distribute 5 Ed25519 key shares to 5 custodians per Part 4.3:
  1. Founder (Khash) — primary
  2. Co-founder / co-director (if added)
  3. CFO / finance lead (if added)
  4. Outside legal counsel
  5. Outside director / board member
- [ ] Each custodian receives share via signed email or in-person USB (NOT Slack/Discord/SMS); confirms receipt
- [ ] **Rehearsal:** `tools/license-sign.sh recover-shamir --dry-run --share-file <3 shares>` produces correct fingerprint
- [ ] **Original ephemeral shares wiped** from tmpfs after distribution
- [ ] `TRUSTED_VENDOR_FINGERPRINT` baked into Hub binary at build time (constant in `license/bundle_verifier.py`)

### 2b. Vendor identity / Keycloak

- [ ] Vendor's own Keycloak instance deployed (NOT customer's; vendor uses it for spine-internal admin + license-signing IAM)
- [ ] Admin realm + spine-vendor-admins group created
- [ ] Custodian Keycloak users provisioned with MFA (TOTP minimum; WebAuthn preferred)

### 2c. Vendor observability

- [ ] **License issuance audit chain** running — every `tools/license-sign.sh sign` invocation writes a hash-chained `spine_audit.audit_event` row in vendor Postgres
- [ ] **Vanta / Drata** in vendor's compliance vault — vendor's own SOC 2 evidence pipeline running (yes, the meta loop: vendor's Spine produces vendor's SOC 2 evidence)
- [ ] **Status page** at `status.spine.dev` (or vendor-chosen domain) — see §6 for infra
- [ ] **Vendor heartbeat** registered: vendor's own Hub heartbeats to its own status registry (Tier 3 self-improvement loop per #27)

## 3. Customer-facing infrastructure

- [ ] **`spine.dev` landing site** live with positioning per `docs/positioning.md`
- [ ] **`try.spine.dev` demo sandbox** provisioned per #15 (public hosted Hub on vendor infra; demo project pre-loaded; "DATA EXPIRES IN 24H" banner; rate-limited; demo-tenant invite path for sales prospects)
- [ ] **`status.spine.dev`** — public uptime/incident page (Statuspage.io or Better Uptime or self-hosted)
- [ ] **`discord.spine.dev`** OR alternative community server — community channel established per closed-source compensation strategy (#18)
- [ ] **`docs.spine.dev`** OR repo-hosted docs — landing-doc set from Wave 5 Squad G publicly readable
- [ ] **DNS + TLS** — Cloudflare or Route 53 + Let's Encrypt; all subdomains verified
- [ ] **Email infrastructure** — `support@spine.dev` + `legal@spine.dev` + `security@spine.dev` + `sales@spine.dev` routing live

## 4. Security pre-flight (closed-source compensations per #18)

- [ ] **SOC 2 Type II observation window** STARTED (per #24 startup-tier; evidence collection automated via shared/audit → Vanta)
- [ ] **Independent pen-test** scoped + scheduled (or completed). Report ready for enterprise sales review.
- [ ] **Source escrow** contract signed (Iron Mountain or NCC Group) — required for top-tier enterprise customers
- [ ] **Bug bounty** program established (or scoped) — even small bounty + responsible-disclosure email
- [ ] **Vulnerability disclosure policy** published at `security.spine.dev/.well-known/security.txt`
- [ ] **TRUSTED_VENDOR_FINGERPRINT** matches the actual Shamir-reconstructable key (manual verification post-distribution)
- [x] **No env-var secret VALUES** anywhere in committed code (final grep audit per #9): `bash tools/audit-secrets.sh` (classifier-aware: distinguishes env-var NAMES, vault paths, obviously-fake test placeholders, and confirmed value leaks). Last run 2026-05-18: zero confirmed value leaks. The raw grep pattern + path-exclude list live inside the audit script; update them there rather than inlining here.
- [x] **TRON dev password rotation (code-side)** — Literal `tron_dev_only` rotated to loud sentinel `tron_LOCAL_DEV_ONLY_2026` across 4 code-default sites (`orchestrator/bin/spine`, `tools/_smoke_phase11_tron.py`, `tools/_tron_alembic_upgrade.py`, `tools/verify-overrides/docker-compose.override.yml`). New helper `tools/_tron_local_default.py` adds a fail-closed guard that refuses sentinel-on-non-loopback connections. Local dev: `cd verify && docker compose down -v postgres && docker compose up -d postgres` to pick up the new password.
- [ ] **TRON prod password population (vault-side)** — Operator must set real values at:
  - TRON Postgres password (vault path `tron/postgres/password`)
  - TRON Redis password (vault path `tron/redis/password`)
  - TRON MinIO admin user + password (vault path `tron/minio/{user,password}`)
  - TRON Grafana password (vault path `tron/grafana/password`)
- [ ] **All vault paths populated with REAL values** (not `InMemoryAdapter`):
  - `spine/postgres/{password,dsn}`
  - `spine/approval/hmac_key`
  - `license/vendor_signing_key` (via Shamir reconstruction)
  - `keycloak/spine-hub/client-secret`
  - `federation/mtls/<role>/{cert,key}`
  - `federation/bearer/<role>`
  - `notify/{slack,email,sms,whatsapp,teams,pagerduty}/...`
  - `evidence/{vanta,drata,secureframe}/api_key`
  - `tron/*` per above rotation

## 5. Deployment-shape verification (each must pass end-to-end)

- [x] **Laptop shape (boot + SPA panels render)** — `bash tools/hub-up.sh` brings up the full 5-container stack (vault + postgres + keycloak-db + keycloak + flyway + hub); 10/10 SPA panels return 200 + `/api/v2/spec` returns the OpenAPI document; healthz returns 200 in dev mode (with `dev_mode: true, db: false` body — InMemoryAdapter doesn't init a DB pool by design); SPA build on host or in-Docker per platform detection (Docker Desktop Mac uses host build to dodge esbuild bugs). OIDC login + Day-0 wizard exercised by `hub/wizard/init.sh` separately. Last verified 2026-05-18.
- [ ] **Vendor-Managed BYOC** — for at least 2 clouds (recommended: AWS + Railway since most-complete per OP2):
  - `tools/byoc/provision.sh --cloud=aws --account=... --hub-version=v1.0.0 --bundle-id=... --admin-email=... --non-interactive` succeeds
  - `tools/byoc/provision.sh --cloud=railway ...` succeeds
  - Hub URL returned; admin login banner printed; first Decision Card "Day-0 bootstrap complete" fires
  - Teardown: `tools/byoc/provision.sh --destroy --cloud=aws --account=...` cleans up
- [ ] **Customer-managed-cloud** — Helm chart smoke-tested on EKS/AKS/GKE (at least 1; AWS recommended)
- [ ] **Self-hosted on-prem** — same Helm chart on vanilla K8s smoke-tested (Rancher Desktop / k3s acceptable for the smoke)
- [x] **DR drill (wiring + dry-run)** — `tools/dr-test.sh --dry-run` validates Python driver wiring; real-run against `file://` target correctly reports `no_completed_backup_run_found` anomaly when DB has no backup history (the failure shape an operator hits before configuring backups, exercised end-to-end). 97/97 recovery tests pass. Last verified 2026-05-18.
- [ ] **DR drill (timed end-to-end RTO ≤ 30 min)** — actual backup→restore→verify cycle against customer-grade infra. Deferred until §6 first design partner run; the laptop loop has no real Postgres state worth restoring, so timing is synthetic. Operator runbook in `docs/DR_RUNBOOK.md`.

## 6. Customer onboarding flow end-to-end

- [ ] **Sign-up form** at `spine.dev/byoc` (or alternative) — collects email + cloud choice + initial bundle config
- [ ] **Delegation instructions** auto-generated per cloud (AWS IAM cross-account role / Azure DAP / GCP SA / Railway team invite / Fly org invite / DO API token)
- [ ] **Credential storage** in vendor vault: `spine-vault kv put kv/byoc/<account>/<cloud>_credentials ...`
- [ ] **Provision script** runs (manual OR via AI agent per #21) — see §5 BYOC
- [ ] **Wizard handoff** — `_state/wizard_manifest.json` + `hub_id.txt` written; admin email receives Hub URL + first-login link
- [ ] **First Decision Card** — "Day-0 bootstrap complete" appears in decision-queue panel within 5 minutes of Hub start
- [ ] **License bundle issuance** — vendor signs initial license bundle for the new customer; cascade through federation tree (vendor → customer-hub)
- [ ] **Customer's first project create** — `spine project new "test" --type feature` succeeds; intake runs

## 7. Launch artifacts (marketing + design partners)

- [ ] **First 3 design partners** identified + onboarded (per #14 ALL segments — solo founder + mid-market + enterprise)
- [ ] **Case study drafts** for each design partner (with their approval) — these replace OSS-stars trust signals per #18
- [ ] **Founder presence** — Twitter/LinkedIn launch post; founder-on-Twitter cadence established
- [ ] **Public roadmap** — v1.1 / v1.2 / v2.0 backlog visible (transparent roadmap = closed-source compensation per #18)
- [ ] **Pricing decision** — per #23 deferred until built+tested; this is the launch trigger to COLLECT FEEDBACK from design partners before committing tiers/$
- [ ] **EULA / MSA / DPA** templates drafted (per #18 closed-source posture; required for enterprise sales)
- [ ] **support@spine.dev triage process** — solo founder = first responder; document SLA expectations honestly (24h business hours v1.0)

## 8. v1.1+ deferred (post-launch backlog — DO NOT block ship on these)

These were intentionally deferred during the v3 build with explicit `NotImplementedError("v1.1+")` stubs or "scaffold" framing. Each is already wired enough that turning it on = small focused work, not architecture.

### Already-scaffolded; needs real impl
- [ ] **Real Twilio voice routing** (TwiML for Master CTO callable-for-incidents)
- [ ] **Native mobile apps** (SwiftUI / Compose; signing wired; placeholder Xcode/Android projects present)
- [ ] **`voice_approve_decision` MCP tool** (`requires_citation=True` per #12)
- [ ] **`channel_voice` feature flag** — add to `KNOWN_FEATURE_FLAGS` + gate Twilio webhook
- [ ] **Tugboat / StrikeGraph / Thoropass compliance exporters** — flip `STUB_V1_1=False` + add real `_render_batch` per vendor
- [ ] **Additional integrations** as `IntegrationAdapter`s — jira / slack / aws / azure / gcp / railway / fly / do connectors (use `shared/integrations/github.py` as template)
- [ ] **Hostinger BYOC** (per #20 long-tail)
- [ ] **AWS/Azure/GCP/Fly/DO live-apply hardening** — dry-run plans complete; live runs need CI-driven tenant-account integration tests
- [ ] **Real `aws sts assume-role` flow** in `tools/byoc/clouds/aws.sh` (~30 lines bash)
- [ ] **Idempotent describe-then-create** per cloud resource
- [ ] **Customer-domain wiring** in BYOC scripts (`--customer-domain=` + Route 53 / Cloudflare integration)
- [ ] **Real graph viz** for federation + kg-search panels (d3-hierarchy or cytoscape; needs `npm install`)
- [ ] **Real upgrade executors** in `migration/spine_version.py` (Flyway / bundle / charter / vault-namespace / KG runners)
- [ ] **Real devops control-plane action implementations** (PyGithub / Terraform SDK / Prometheus / PagerDuty / Argo CD / Flyway / Route53 per plane)
- [ ] **vault unseal recovery integration** — `tools/license-sign.sh recover-shamir` for adapters beyond HashiCorp / OpenBao (AWS SM / Azure KV / GCP / Infisical / 1Password)

### Architecture upgrades (post-traction)
- [ ] **Cross-region DR active-passive** (#32 layer 7 — enterprise tier `dr.cross_region` flag)
- [ ] **Postgres-backed quota counters** (per-org spine_license.feature_flag rows + WAVE 4.5 quota refit)
- [ ] **Postgres-backed decision queue** end-to-end (currently write-through cache; promote to DB-first)
- [ ] **Move `_BucketStore` to Redis** for multi-Hub rate-limit fan-out
- [ ] **`shared.runtime.session_store`** federation-aware replacing process-local dict
- [ ] **NON-UUID federation hub_id persistence** — slug column on V23 OR refuse non-UUID at API
- [ ] **Streaming role-chat replies** (currently single-shot)
- [ ] **SSE reconnect/backoff** for SPA SSE consumers
- [ ] **Air-gapped deployment shape** (per #17 — currently v1.1 deferred)

### Cleanup
- [ ] **Stale `verify/tests/unit/test_llm_client*.py`** — pre-existing tests that monkeypatched the deleted `_call_anthropic`/`_call_openai`/`_call_ollama` methods (now stale after OP1 TRON LLM bridge); retire or rewrite
- [ ] **`secrets.tests` namespace shadow** breaking combined pytest runs — pre-existing collection bug
- [ ] **Pre-existing `test_remote_round_trip.py` secrets/__init__.py shadow** breaking Starlette's `from secrets import token_hex` — same root cause
- [ ] **CHANGELOG.md** v3 update (pre-conversation drift; not in this build's scope)
- [ ] **CLAUDE.md / repo-root meta-docs** still describe v1 file-bus framing — refresh post-launch

---

## Launch sign-off

Once all of §1-§7 are checked AND §0 sanity passes:

- [ ] **First design partner runs through Day-0 wizard end-to-end** without founder intervention (proves the AI-drivable Hub bootstrap works without solo human in the loop)
- [ ] **Founder sign-off**: Khash signs this checklist
- [ ] **Tag release**: `git tag v1.0.0 -s -m "Spine v1.0 — AI software company in a box"`
- [ ] **Public announcement**: Twitter / LinkedIn / Discord / public roadmap announcement
- [ ] **STATUS.md updated**: mark "v1.0 SHIPPED" + capture launch-week metrics tracking plan

---

**Document control:**
- Created: 2026-05-18 (post Wave 3.5 + OP1/OP2/OP3 ship-gate work)
- Author: AI orchestration (Claude Opus 4.7), reviewed by Khash Sarrafi
- Status: **CANONICAL** — single source of truth for v1.0 launch readiness
- Supersedes: any earlier "what's left" lists in `docs/STATUS.md` for the launch decision
- Next update trigger: anything checked here, OR a new operational gate discovered during launch dry-runs
