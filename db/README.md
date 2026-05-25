# Spine Database — Postgres backbone

> Postgres is the single backbone for the Spine Hub: lifecycle state, KG, audit, cost, memory, eval, verify, license, federation, evidence, identity, devops, work-items, learning, provider catalog, cloud catalog, DR backup log. One instance, many schemas, **one source of structured truth.**
>
> Drivers: [`docs/V3_DESIGN_DECISIONS.md`](../docs/V3_DESIGN_DECISIONS.md) — #3 (Hub-as-product), #9 (vault-only secrets), #15 (NOT SaaS — Postgres lives in customer's cloud / on-prem / laptop), #17 (4 shapes), #24 (audit-chain → evidence), #31/32 (DR).
>
> Pre-v3 file-bus-watcher mode (per-role outbox.jsonl drained by `watcher/`) is archived at `docs/_archived/v2-db-README.md`. The v3 Hub writes directly into Postgres via `shared/api/` over an asyncpg pool; the watcher is retained only for legacy multi-machine fleet mode and is being retired.

---

## What this is

A versioned Postgres schema (Flyway-migrated) holding every piece of structured state the Hub needs:

- **Lifecycle** — projects, phases, work-items, decisions
- **KG** — code/document knowledge graph (nodes + edges + embeddings via pgvector)
- **Audit** — hash-chained ledger; every action across every subsystem writes here
- **Cost** — unified cost ledger; per-provider usage, per-user/org budget enforcement
- **Memory** — 3-tier scope (per-project / within-Hub / cross-org per #27)
- **Verify** — TRON-grade verify results, calibration corpus
- **License** — signed bundles, feature flags, hash-chained quota usage (V22)
- **Federation** — hub registry, parent/child relationships, update cascade events (V23)
- **Hub** — project registry per Hub, hub_id stable across restarts (V24)
- **Evidence** — collectors output, two-party attestation hashes (V25)
- **Identity** — Keycloak realm link, group/role mapping (V26)
- **DevOps** — role state, 8 control-plane scoped events (V27)
- **Work-items** — 7 types per #19 with per-type schemas (V28)
- **Learning** — 3-tier lessons, anonymized telemetry, consent registry (V29)
- **Provider catalog** — 7 LLM providers (#2) + per-provider model metadata (V30)
- **Cloud catalog** — 5+ clouds Day 1 (#20) + per-cloud capability flags (V31)
- **DR backup log** — backup runs + restore tests + verification (V32)

---

## How to run (laptop shape)

Postgres and TRON Postgres both come up under **`hub/docker-compose.yml`** (Docker Compose project **`spine-hub`**). Use `bash tools/hub-up.sh` for the full Hub stack, or `make bootstrap` for databases + migrations only.

```bash
bash tools/hub-up.sh              # vault + postgres + tron-postgres + flyway + hub
make bootstrap                    # postgres + tron-postgres + flyway + alembic + smoke
```

The legacy **`db/docker-compose.yml`** stack (project name `db`, container `spine_postgres` on port 33001) is **deprecated** for laptop dev — do not run it alongside the Hub (duplicate Spine Postgres). The file-bus **watcher** service remains for archived fleet mode only.

```bash
make db-psql             # opens psql against spine-hub-postgres (port 33099)
```

For BYOC / customer-cloud / on-prem, Postgres is provisioned by the deployment shape:

- **BYOC:** Spine vendor provisions a managed Postgres (RDS / Cloud SQL / Azure Database for PostgreSQL) into customer's account
- **Customer-cloud:** Helm chart deploys Postgres via Bitnami chart OR uses customer's existing managed Postgres (set `--set postgres.external.url=...`)
- **On-prem:** customer's existing Postgres (HA cluster / Patroni / etc.) — point Hub at it via `SPINE_DB_URL` (resolved from vault per #9)

**Credentials always flow through vault** (#9). No `db/.env` plaintext credentials in v3 — the v2 `spine / spine_dev_only` dev-only password posture is dead.

---

## Schema versions

Versioned via Flyway; migrations in `flyway/sql/` applied in lexical order. Each `V<N>__<name>.sql` is irreversible by convention (forward-only); `R__<name>.sql` are repeatable seed/refresh scripts.

### Core v1–v21 (KEEP)

| Version | What it adds |
|---|---|
| `V1__init_core_schema.sql` | 19-table core: job_family, discipline, level, tier, provider, model, role, team, worker, task, prompt, prompt_version, assignment, directive, report, artifact, review, handoff, cost_row, team_memory, worker_memory, rollback_entry, event |
| `R__1_seed_lookups.sql` | Seed tiers, levels, disciplines, job families, default roles |
| `R__2_model_pricing.sql` | Per-model token pricing (refreshed when providers change pricing) |
| `V2__spine_kg_schema.sql` | KG nodes + edges + embeddings (pgvector); 8 MCP tools query this |
| `V3__multi_host.sql` | Multi-machine fleet (legacy v1.4 multi-laptop pattern) |
| `V4__views.sql` | 5 read-side views: `v_cost_by_role_day`, `v_cost_by_model`, `v_active_workers`, `v_recent_events`, `v_cost_by_outcome` |
| `V5__invocation_durations.sql` | Wall-clock duration on cost rows |
| `V10__artifacts_index.sql` | Artifact lookup index |
| `V11__tenant_scoping.sql` | Tenant scoping for hosted fleet |
| `V12__spine_releases.sql` | Release channel registry (stable / beta / canary) |
| `V13__machine_vitals.sql` | Per-instance vitals (CPU/mem/disk/load + Spine-attributed totals) |
| `V14__spine_lifecycle_schema.sql` | Project lifecycle state machine |
| `V15__spine_audit_schema.sql` | **Hash-chained audit ledger** (foundation for #24 evidence pipeline) |
| `V16__unified_cost_ledger.sql` | Unified cost across Plan + Build + Verify subsystems |
| `V17__portfolio_views.sql` | Portfolio aggregates across multi-project Hubs |
| `V18__calibration_corpus.sql` | Calibration outcomes per role (Platt scaling input) |
| `V19__spine_eval_schema.sql` | Eval harness results (golden-suite on every release) |
| `V20__spine_memory_schema.sql` | Memory writer hooks (7 trigger points per #27) |
| `V21__spine_verify_schemas.sql` | Verify schemas (TRON-bridged) |

### v3 additions V22–V35 (Wave 0 + Wave 1 + Wave 2 + Wave 3)

Per `docs/V3_BUILD_SEQUENCE.md` Wave 0 deliverables + downstream CHECK extensions:

| Version | Subsystem | Driver | What it adds |
|---|---|---|---|
| **`V22__license_registry.sql`** | license/ | #23 | `spine_license.bundle` (signed Ed25519 bundle blob + fingerprint + verified_at) + `spine_license.quota_usage` (hash-chained per-feature usage ledger) + `spine_license.feature_grant` (which flags ON for current bundle) |
| **`V23__federation_registry.sql`** | federation/ | #4 #10 #16 | `spine_federation.hub` (UUIDv4 hub_id + parent_hub_id + role + bundle_version) + `spine_federation.consent_grant` (per-tool peer-consent records) + `spine_federation.update_cascade_event` (vendor → parent → child distribution audit) |
| **`V24__hub_project_registry.sql`** | hub/ | #3 | `spine_hub.project` (per-Hub project registry — different from `spine_lifecycle.project` which is global) + `spine_hub.master_role_state` (per-Hub Master role context) |
| **`V25__evidence_store.sql`** | evidence/ | #24 | `spine_evidence.collector_output` + `spine_evidence.export_status` (per-GRC push state) + `spine_evidence.attestation` (SHA-256 two-party hashes — customer auditor + Spine chain) |
| **`V26__keycloak_link.sql`** | shared/identity + keycloak/ | #25 | `spine_identity.keycloak_realm` (realm linkage) + `spine_identity.group_mapping` (Keycloak groups → Spine RBAC scopes) + `spine_identity.user_attribute` (per-user comm prefs per #6, tier per #14) |
| **`V27__devops_role.sql`** | devops/ | #11 | `spine_devops.plane_state` (8 control planes: compute / network / data / identity / secrets / observability / incident / workspace-hygiene) + `spine_devops.runbook_link` |
| **`V28__work_item_types.sql`** | plan/ + build/ | #19 | `spine_workitem.type` enum (feature / bug / incident / support / refactor / infra / compliance) + per-type intake template ref + per-type pipeline variant |
| **`V29__smart_spine_learning.sql`** | learning/ | #27 | `spine_learning.lesson` (3-tier scope: project/within_hub/cross_org) + `spine_learning.consent` (per-data-class cross-org opt-in) + `spine_learning.telemetry_export` (anonymized payload + redaction proof) |
| **`V30__provider_catalog.sql`** | shared/llm | #2 | `spine_provider.adapter` (anthropic / openai / bedrock / vertex / ollama / qwen / vllm) + `spine_provider.model` (per-provider model + pricing + capability flags) |
| **`V31__cloud_targets.sql`** | devops/ + tools/ | #17 #20 | `spine_cloud.target` (aws / azure / gcp / railway / fly / digitalocean / hostinger + per-cloud capability flags + BYOC delegation mechanism) |
| **`V32__dr_backup_log.sql`** | recovery/ | #31 #32 | `spine_recovery.backup_run` (per-layer backup attempts) + `spine_recovery.restore_test` (weekly test results) + `spine_recovery.verification_run` (per-release backup compat verification, layer 12) |
| **`V33__audit_subsystem_extension.sql`** | shared/audit | Wave 2 | Extend `audit_record.subsystem` CHECK to include `hub`, `federation`, `integration` |
| **`V34__cross_llm_provider_backfill.sql`** | shared/validation | #2 | Backfill `cross_llm.provider` enum to all 7 providers (was 2 in v2) |
| **`V35__audit_subsystem_devops.sql`** | shared/audit | Wave 3 | Extend `audit_record.subsystem` CHECK to include `devops` (Wave 3 Squad A) |

### Schemas at v3 ship (logical separation, single instance)

```
spine_pg
├── public.            v1 core 19-table seed (KEEP for legacy)
├── spine_kg.          knowledge graph (V2)
├── spine_lifecycle.   project lifecycle (V14)
├── spine_audit.       hash-chained ledger (V15) — the SOC 2 evidence foundation (#24)
├── spine_cost.        unified cost (V16)
├── spine_memory.      3-tier lessons (V20)
├── spine_eval.        golden-suite results (V19)
├── spine_verify.      TRON-bridged verify (V21)
├── spine_license.     license bundles + quota (V22)
├── spine_federation.  hub registry + consent + cascade (V23)
├── spine_hub.         per-Hub project + master state (V24)
├── spine_evidence.    collectors + GRC export + attestation (V25)
├── spine_identity.    Keycloak link + RBAC + per-user prefs (V26)
├── spine_devops.      8 control planes (V27)
├── spine_workitem.    7 work-item types (V28)
├── spine_learning.    Smart Spine 3-tier (V29)
├── spine_provider.    LLM provider catalog (V30)
├── spine_cloud.       cloud target catalog (V31)
└── spine_recovery.    DR backup log (V32)
```

---

## Postgres-specific choices

- **Primary keys:** UUIDv4 with `DEFAULT gen_random_uuid()` (via `pgcrypto`). Lookup tables keep text natural keys.
- **Timestamps:** `TIMESTAMPTZ DEFAULT now()`.
- **JSON:** `JSONB` with `'{}'::jsonb` defaults.
- **Enums:** real `ENUM` types for closed status sets (`worker_status`, `task_status`, `assignment_status`, `review_status`, `artifact_kind`, `spine_workitem.type`, `spine_federation.consent_class`, etc.)
- **Audit hash chain:** `spine_audit.record.row_hash = sha256(prev_row_hash || canonical(row))`. Tamper detection via `tools/audit-verify-chain.py`.
- **Quota ledger:** `spine_license.quota_usage.hash_chain` mirrors audit-chain pattern — feature-flag enforcement at every gate writes a row; chain proves no replay/deletion.
- **pgvector:** `spine_kg.node.embedding` `vector(1536)` for OpenAI / Anthropic / Cohere embeddings; `vector(768)` for local providers.
- **Triggers:** shared `set_updated_at()` trigger keeps `updated_at` columns fresh on hot tables.

---

## Connection + credentials (#9)

In v3, the Hub resolves `SPINE_DB_URL` from vault, not env vars:

```python
# Inside hub container (FastAPI lifespan)
from shared.secrets import get_secret
dsn = get_secret("spine_pg/dsn")   # vault path; rotated by spine_pg/rotation policy
```

**No** `db/.env` **with plaintext credentials in v3.** The v2 `spine / spine_dev_only` dev-only password is the only thing that should ever appear in a `.env`-like file — and even that is being phased out for laptop shape where the wizard writes the DSN straight into vault.

Adapter mapping by deployment shape:

| Shape | Vault adapter | DB credentials source |
|---|---|---|
| Laptop | OpenBao bundled | Wizard generates random PG pass, writes to OpenBao, Hub reads from OpenBao |
| BYOC | Cloud-native (AWS Secrets Manager / Azure Key Vault / GCP Secret Manager) | Vendor automation provisions managed PG + writes DSN to customer's vault |
| Customer-cloud | Per customer (HashiCorp Vault / cloud-native) | Customer's existing vault stores DSN; Helm chart consumes |
| On-prem | HashiCorp Vault (typical) | Customer's existing vault stores DSN |

---

## Common operations

```bash
# psql shell
make db-psql

# Flyway info (which migrations applied)
make db-info

# Validate applied migrations against SQL files (drift detection)
make db-validate

# Restore from backup (DR layer 4 — recovery/)
spine recovery restore --backup-id <id>

# Run DR test (DR layer 4 — weekly restore-to-throwaway)
bash tools/dr-test.sh
```

Migrations apply on Hub `up` (Flyway runs as a one-shot dependency before the Hub container starts; see `hub/docker-compose.yml`). The Hub refuses to start if migrations fail.

---

## Multi-machine fleet (legacy)

The pre-v3 "Spine Hub" pattern (Pass H + Pass M + Pass L) is being retired in favor of #3 (real Hub container) + #4 (federation control plane). The legacy `share-pg.sh` + `spine-connect.sh` + `spine-disconnect.sh` flow is preserved during Wave 5 transition but will be removed in Wave 6 along with the rest of `lib/`. For v3 multi-Hub deployments, see [`docs/FEDERATION_GUIDE.md`](../docs/FEDERATION_GUIDE.md).

---

## Backups + DR

Per #31 + #32 + the 12-layer DR architecture, this Postgres has DR built in:

- **Layer 3 — continuous backup:** PG WAL streamed to customer's chosen S3-compatible storage (S3 / GCS / Azure Blob / MinIO / Wasabi), KMS-encrypted, default 30d retention per bundle policy
- **Layer 4 — tested restore:** weekly `tools/dr-test.sh` restores to throwaway environment, verifies Hub functional in < 30 min
- **Layer 7 — cross-region replication:** optional per bundle (enterprise tier flag `dr.cross_region`); active-passive standby in second region
- **Layer 12 — backup verification on release:** when vendor publishes new Spine version, customer's automated DR test re-validates restore against new version

Full DR runbook: [`docs/DR_RUNBOOK.md`](../docs/DR_RUNBOOK.md). Per-deployment auto-generated runbook lives at `_state/dr_runbook.md` after `hub/wizard/init.sh`.

---

## Safety notes

- **Never** reuse the dev `spine_dev_only` password outside a localhost-bound development Postgres.
- **Never** put credentials into `db/.env` for production — flow through vault (#9).
- **Never** disable hash chain verification on `spine_audit` — that's the SOC 2 evidence foundation. Tampering invalidates two-party attestation (#24).
- **Never** restore a backup that fails verification — `spine recovery restore` blocks on hash-chain integrity check by design.

---

## Related artifacts

- [`docs/V3_DESIGN_DECISIONS.md`](../docs/V3_DESIGN_DECISIONS.md) — driver decisions for every V22+ schema
- [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) §5 — cross-cutting tech stack
- [`docs/SECURITY_GUIDE.md`](../docs/SECURITY_GUIDE.md) — vault posture + audit-chain integrity
- [`docs/DR_RUNBOOK.md`](../docs/DR_RUNBOOK.md) — backup + restore + verification operationally
- [`docs/LICENSING_GUIDE.md`](../docs/LICENSING_GUIDE.md) — V22 license_registry detail
- [`docs/FEDERATION_GUIDE.md`](../docs/FEDERATION_GUIDE.md) — V23 federation_registry detail
- Per-schema READMEs alongside their SQL files (`V<N>__<name>.README.md`) for schemas that have them
