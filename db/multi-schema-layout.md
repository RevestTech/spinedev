# Spine Multi-Schema Layout

Single Postgres instance, multiple schemas, **one** migration tool (Flyway).
Reference: `docs/ARCHITECTURE.md` §3 R-2 ("one Postgres instance, multiple
schemas with clear ownership") and §6 Phase 2.

## Schemas

| Schema | Owning migration | Purpose | Notable tables |
|---|---|---|---|
| `public` | V1..V13 (legacy) | Original Spine v1 recording layer; instance/engagement/artifact bookkeeping | `event`, `cost_row`, `spine_instance`, `engagement`, `engagement_artifact`, `engagement_link`, `machine_vitals`, `spine_releases` |
| `spine_kg` | V2 | Knowledge graph + embeddings | `kg_node`, `kg_edge`, `kg_node_embedding`, `kg_node_property`, `kg_index_state` |
| `spine_lifecycle` | V14 | Orchestrator state machine | `project`, `phase_history`, `transition`, `approval`, `route_history`, `portfolio_queue` (V17) |
| `spine_audit` | V15 | Append-only unified audit log | `audit_event` |
| `spine_recording` | V16 | Unified cost ledger | `costs` |
| (views) | V17 | Portfolio views over lifecycle + recording | `v_portfolio_summary`, `v_cost_per_org`, ... |
| `spine_calibration` | V18 | LLM confidence calibration | `prediction`, `outcome`, `calibration_model` |
| `spine_eval` | V19 | Role-prompt eval harness | `dataset`, `eval_run`, `case_result` |
| `spine_memory` | V20 | Vector-backed per-role lesson store | `lesson`, `retrieval_log` |
| `spine_verify_audit` | V21 | TRON verify-internal | `audit_run`, `finding`, `code_file`, `file_dependency`, `finding_relationship`, `agent_metrics`, `cross_validation`, `api_key` |
| `spine_verify_threat_intel` | V21 | Normalized advisories (CVE/GHSA/OSV) | `advisory` |

## Ownership rules

- **Flyway is the single source of truth** for all schemas. TRON's existing
  `verify/alembic/` is frozen after subtree merge; V21 squashes the TRON
  baseline (`001..008`) into Flyway. See `db/migration-survey.md`.
- **Each schema has one owning story** (above table). Cross-story PRs that
  modify another schema need explicit sign-off from that schema's owner.
- **Migration numbers are monotonic** across the whole repo — no per-schema
  numbering. A migration that touches several schemas (e.g., a view) gets
  one number.

## Privileges (target — implemented incrementally)

| Role | Read | Write | Notes |
|---|---|---|---|
| `spine_app` | all `spine_*` schemas + `public` | non-audit `spine_*` schemas it owns | Default app role |
| `spine_audit_writer` | — | `INSERT` only on `spine_audit.audit_event` | Append-only (V15 design) |
| `spine_lifecycle_writer` | own schema | `spine_lifecycle.*` | Orchestrator state machine |
| `spine_recording_writer` | own schema | `spine_recording.costs` | Cost recorder |
| `spine_verify_writer` | own schemas + `spine_recording` (for cost mirroring) | `spine_verify_*.*` | TRON workers |
| `spine_readonly` | all schemas | — | Dashboards, BI |

Role provisioning script lives at `shared/db/roles.sql` (Phase 2 deliverable —
not in this story). Until then, all writes use the bootstrap superuser
defined in `db/.env`.

## Cross-schema queries

- **Allowed**: views (e.g., `v_cost_per_org` joins `spine_recording.costs` +
  `spine_lifecycle.project`). Materialized views OK if refresh strategy
  documented in the migration README.
- **Discouraged**: hot-path application queries that span schemas without a
  view. Wrap in a view so the join is reviewable in SQL, not buried in
  application code.
- **FKs across schemas**: kept loose (declared in `db/conventions.md` and
  per-migration READMEs). This preserves migration-order flexibility and
  lets schemas be dropped/restored independently. Example: V21
  `spine_verify_audit.audit_run.project_uuid` references the lifecycle
  project by UUID, with an advisory `project_id BIGINT` column reserved for
  a future hard FK once TRON code populates it.

## Backup strategy

- **Default**: single `pg_dump` covers all schemas. Restore is atomic.
- **Per-schema dump** available via `pg_dump --schema=<name>` for partial
  restore. Useful for blast-radius-limited recovery of TRON-internal data
  without touching lifecycle/audit.
- **Audit immutability**: `spine_audit.audit_event` is NEVER restored
  partially or rewritten. A full audit restore requires a full DB restore;
  point-in-time recovery via WAL is the operational recipe.

## Extensions baseline

Created early and re-asserted by individual migrations via `CREATE EXTENSION
IF NOT EXISTS`:

- `pgcrypto` (V1, V2, V14, V15, V18..V21) — `gen_random_uuid()`.
- `vector` (V20) — pgvector for `spine_memory.lesson_embedding` and
  `spine_kg.kg_node_embedding` (768-dim).
- `ltree` (V1, V2) — hierarchical paths (directory_path, hierarchy_path).
- `pg_trgm` (V1, V21) — fuzzy text search on paths/titles.
- `btree_gist` (V1, V21) — composite GIST indexes.

## Migration ownership of TRON

- V21 squashes the TRON Alembic baseline.
- Tables NOT duplicated by V21 (see `db/migration-survey.md` "Schema
  mapping"): `tron.llm_usage`, `tron.llm_cost_*`, `tron.projects` core,
  `tron.standards`. TRON code must be updated to query the Spine canonical
  schemas in a follow-up story.
- Once TRON code is fully migrated, `verify/alembic/` is decommissioned and
  the `alembic_version` row dropped.

## Cross-refs

- `db/migration-survey.md` — TRON Alembic → Flyway port survey.
- `db/migrate-to-shared.sh` — STORY-8.3.3 `db/` → `shared/db/` helper.
- `docs/ARCHITECTURE.md` §3 R-2, §6 Phase 2.
- `docs/PRD.md` REQ-INIT-8 §8.5 FR-3.
- `docs/BACKLOG.md` INIT-8 EPIC-8.3.
