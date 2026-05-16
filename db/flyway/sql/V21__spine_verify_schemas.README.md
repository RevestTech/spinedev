# V21 — spine_verify schemas

Ports TRON's Alembic baseline (`verify/alembic/versions/001..008`) into
Flyway. See `db/migration-survey.md` for the per-revision mapping.

## Numbering note

The story spec referenced `V20`, but `V20__spine_memory_schema.sql` already
exists (STORY-4.2 lesson store). This migration therefore lives at **V21**.
Future verify-domain migrations follow at V22+.

## What this migration creates

Schemas:

- `spine_verify_audit` — TRON's verify-internal tables (audit_run, finding,
  code_file, file_dependency, finding_relationship, agent_metrics,
  cross_validation, api_key) + verify-domain enums.
- `spine_verify_threat_intel` — normalized advisory rows (CVE/GHSA/OSV).

Enum types in `spine_verify_audit`:

- `vulnerability_type`, `severity_level`, `cross_validation_status`,
  `consensus_level`, `audit_run_status`, `execution_outcome` — mirror
  `verify/tron/schemas/verification.py`.

## What this migration DOES NOT do

Per `db/migration-survey.md`, these TRON tables are NOT duplicated; TRON
code must migrate to read/write the canonical Spine location:

| TRON Alembic table | Canonical Spine location | Migration owner |
|---|---|---|
| `tron.llm_usage`, `tron.llm_cost_*` | `spine_recording.costs` (V16) | TRON code-side change |
| `tron.projects` (core fields) | `spine_lifecycle.project` (V14) | TRON code-side change |
| `tron.projects.*_json` blobs | `spine_lifecycle.project.metadata` | TRON code-side change |
| `tron.standards` | `shared/standards/` (file-based) | Future schema story |
| `tron.cost_events`, `tron.project_cost_limits` | Future `spine_budget` schema | Deferred |

## Cross-schema FK posture

- **Within `spine_verify_audit`** — FKs declared (`audit_run` → `finding`,
  `code_file` → `finding`, `finding` → `finding_relationship`).
- **Across schemas** — none in V21. `audit_run.project_uuid` is loose; an
  advisory `project_id BIGINT` column is reserved for a follow-up FK to
  `spine_lifecycle.project(id)` once TRON's code populates it.

## Test plan

1. `make migrate` runs V21 cleanly on a Postgres with V1..V20 applied.
2. `psql \dn` shows both new schemas.
3. `psql \dt spine_verify_audit.*` shows 8 tables.
4. `psql \dT spine_verify_audit.*` shows 6 enum types.
5. `sqlfluff lint --dialect postgres db/flyway/sql/V21__spine_verify_schemas.sql`.
6. Insert smoke: one `audit_run`, one `finding`, one `agent_metrics`,
   one `cross_validation`, one `advisory`.

## Cross-refs

- `docs/PRD.md` REQ-INIT-8 §8.5 FR-3.
- `docs/ARCHITECTURE.md` §4 (multi-schema), §6 Phase 2.
- `docs/BACKLOG.md` INIT-8 EPIC-8.3 STORY-8.3.1.
- `db/migration-survey.md` — port plan.
- `db/multi-schema-layout.md` — canonical schema map.
- `verify/alembic/versions/001..008.py` — source migrations.
- `verify/tron/schemas/verification.py` — enum source.
