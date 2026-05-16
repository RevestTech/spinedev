# TRON Alembic → Spine Flyway Migration Survey

Survey of TRON's Alembic migrations (`verify/alembic/versions/`) with port
plan into Spine Flyway (`db/flyway/sql/`). Inputs: `docs/ARCHITECTURE.md` §6
Phase 2, `docs/PRD.md` REQ-INIT-8 FR-3, `docs/BACKLOG.md` EPIC-8.3.

## Version-number note

Task spec referenced `V20`, but `V20__spine_memory_schema.sql` already exists
(STORY-4.2 lesson store). This survey and the actual SQL file therefore use
**`V21__spine_verify_schemas.sql`**. Future TRON-domain migrations follow at
`V22+`.

## TRON migrations inventory

| Alembic ver | Slug | Tables / columns touched | Spine target | Porting status |
|---|---|---|---|---|
| `001` | initial_schema | `projects`, `audit_runs`, `code_files`, `findings`, `llm_usage`, `llm_cost_hourly`, `llm_cost_daily`, `project_cost_limits`, `cost_events`, `file_dependencies`, `finding_relationships`, `standards` + extensions (`ltree`, `pg_trgm`, `btree_gist`, `uuid-ossp`) + `update_updated_at_column()` trigger | `spine_verify_audit.*` for verify-internal tables; `spine_recording.costs` already covers `llm_usage`/`llm_cost_*`; `spine_lifecycle.project` overlaps with `projects`; `spine_kg.*` overlaps with `code_files`/`file_dependencies` | **Partial port (V21).** Port `audit_run`, `finding`, `cross_validation`, `agent_metrics`, `code_file`, `file_dependency`, `finding_relationship` into `spine_verify_audit`. `llm_usage` / `llm_cost_*` → DO NOT duplicate (use `spine_recording.costs`). `projects` → DO NOT duplicate (use `spine_lifecycle.project`). `standards` → DO NOT duplicate (use `shared/standards/` + future schema). Flag code-side migration. |
| `002` | project_proposal_fields | `projects.quality_gates_json`, `plan_artifact_json`, `last_build_result_json` | `spine_lifecycle.project.metadata` JSONB (existing) | **Map to existing.** No new column; TRON code must read/write through the lifecycle project metadata. |
| `003` | company_quality_gates | `projects.company_quality_gates_json` | `spine_lifecycle.project.metadata` JSONB | **Map to existing.** Same as 002. |
| `004` | plan_questionnaire | `projects.plan_questionnaire_json` | `spine_lifecycle.project.metadata` JSONB | **Map to existing.** Same as 002. |
| `005` | api_keys | `api_keys` (label, key_hash, scopes JSONB, active, timestamps) | `spine_verify_audit.api_key` (TRON-scoped API surface) | **Port (V21).** Verify-only API keys live with verify. Spine-wide API auth is a separate, larger story. |
| `006` | evolve_and_compliance_packs | `projects.evolve_artifact_json`, `compliance_control_pack_ids` | `spine_lifecycle.project.metadata` JSONB; compliance pack IDs → `spine_lifecycle.project.org_bundle` resolution | **Map to existing.** |
| `007` | agent_handoff_path | `projects.agent_handoff_path` | `spine_lifecycle.project.metadata` JSONB (key `agent_handoff_path`) | **Map to existing.** Worker host path; not a project property. |
| `008` | threat_intel_alerts | `audit_runs.threat_intel_alerts_json` | `spine_verify_threat_intel.advisory` table + JSONB column on `spine_verify_audit.audit_run.metadata` | **Split port (V21).** Normalized advisory rows live in dedicated schema; per-audit-run snapshot retained as JSONB. |

## Strategy

- **Verify-internal tables** (`audit_run`, `finding`, `code_file`, `file_dependency`, `finding_relationship`, `cross_validation`, `agent_metrics`, `api_key`) → port to **`spine_verify_audit`** schema.
- **Threat intel** → dedicated **`spine_verify_threat_intel`** schema with normalized `advisory` rows.
- **Overlaps already covered by Spine schemas** → DO NOT duplicate; TRON's code must be updated in a follow-up to query the canonical Spine schema:
  - `tron.llm_usage` / `tron.llm_cost_*` → `spine_recording.costs` (V16 unified cost ledger).
  - `tron.projects` core fields → `spine_lifecycle.project` (V14).
  - `tron.projects.*_json` blobs → `spine_lifecycle.project.metadata` JSONB.
  - `tron.standards` → `shared/standards/` (file-based) + future `spine_standards` schema; out of scope here.
- **Enums** (`VulnerabilityType`, `ConsensusLevel`, `CrossValidationStatus`, `SeverityLevel`, `ExecutionOutcome`) → port as Postgres `ENUM` types in `spine_verify_audit`. Stays in lockstep with `verify/tron/schemas/verification.py`.
- **Alembic baseline** (001) → squashed into V21; subsequent TRON ALTERs (002-008) → either folded into V21 (the new normalized tables already include the fields) or explicitly recorded as "map-only" with TRON code-side change required.
- **Extensions** (`ltree`, `pg_trgm`, `btree_gist`, `uuid-ossp`, `pgcrypto`, `vector`) → most already created by V1/V2/V20; V21 only re-asserts what it needs via `CREATE EXTENSION IF NOT EXISTS`.

## Schema mapping (canonical)

| TRON table/column | Spine canonical location | Notes |
|---|---|---|
| `tron.audit_runs` | `spine_verify_audit.audit_run` | UUID PK preserved; `project_id` becomes `BIGINT` FK candidate to `spine_lifecycle.project(id)`, kept loose pending code migration. |
| `tron.findings` | `spine_verify_audit.finding` | Fingerprint dedup preserved; `audit_run_id` FK within schema. |
| `tron.code_files` | `spine_verify_audit.code_file` | Mirrors `spine_kg.kg_node` for files-as-nodes; full convergence later. |
| `tron.file_dependencies` | `spine_verify_audit.file_dependency` | Mirrors `spine_kg.kg_edge`; full convergence later. |
| `tron.finding_relationships` | `spine_verify_audit.finding_relationship` | Stays verify-internal. |
| `tron.llm_usage` / `tron.llm_cost_*` | `spine_recording.costs` (V16) | TRON code-side migration: route through `shared/cost/`. |
| `tron.cost_events` / `tron.project_cost_limits` | `spine_recording.costs` (V16) + future budget schema | Deferred to STORY-9.7 budget story. |
| `tron.projects` | `spine_lifecycle.project` (V14) | Project lifecycle is owned by orchestrator. |
| `tron.standards` | `shared/standards/` + future schema | Hierarchy lives in file system + org bundle resolution. |
| `tron.api_keys` | `spine_verify_audit.api_key` | Verify-scoped only; Spine-wide auth is separate. |
| `tron.audit_runs.threat_intel_alerts_json` | `spine_verify_threat_intel.advisory` (normalized) + `spine_verify_audit.audit_run.metadata` snapshot | Hybrid: normalized rows for analytics, JSONB for run snapshot. |
| Enums (`VulnerabilityType`, etc.) | `spine_verify_audit.<enum>` Postgres ENUMs | Names mirror Pydantic. |

## TRON code-side follow-up work (out of scope here)

Documented for the follow-up story:

1. Replace `tron.infra.db.models.Project` queries → `spine_lifecycle.project` SQLAlchemy mapping under `shared/db/`.
2. Replace `tron.LLMUsage` writes → `shared/cost/recorder.py` → `spine_recording.costs`.
3. Move JSONB blobs (`quality_gates_json`, `plan_artifact_json`, etc.) into `spine_lifecycle.project.metadata` JSONB; provide JSON-path accessors in `tron/services/`.
4. Repoint Alembic stamp: once TRON's queries target Spine schemas, `verify/alembic/` is decommissioned and `alembic_version` row removed.

## Open questions

- **Should TRON tables that are project-id keyed share Spine's `spine_lifecycle.project` table?** Recommendation: yes — share via FK to `spine_lifecycle.project(id)` once TRON's code is updated; for now V21 mirrors the UUID column (`project_uuid UUID`) and adds an advisory `project_id BIGINT` column populated by an application-side lookup. No DB-level FK in V21 to avoid coupling migration order.
- **Flyway monotonic vs. Alembic revision strings.** Alembic versions don't follow Flyway monotonic. V21 squashes the entire TRON baseline; subsequent TRON migrations (post-subtree) become V22+.
- **Will TRON ship its own further Alembic revisions during Phase 1?** If yes, those must be hand-ported as new Flyway files (e.g., V22, V23). The TRON team agreed to freeze new Alembic revisions after subtree merge per ARCHITECTURE §6 Phase 2.
- **`uuid-ossp` vs `pgcrypto::gen_random_uuid()`.** Spine already standardizes on `pgcrypto` (`gen_random_uuid()`); V21 uses `pgcrypto` everywhere, drops the `uuid-ossp` dep created by TRON's 001.
