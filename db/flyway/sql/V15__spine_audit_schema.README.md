# V15 — Spine unified audit log

Implements `STORY-3.1.1` (audit record schema) and `STORY-3.1.2` (storage =
Postgres) from `docs/BACKLOG.md`, satisfying REQ-INIT-9 FR-8 and feeding
REQ-INIT-7 FR-3, REQ-INIT-8 FR-4, REQ-INIT-1 FR-5.

## Why one audit table for the whole product

The killer compliance question is cross-subsystem: "show me everything that
happened to project 42 across Plan + Build + Verify + Orchestrator." That
stays a single `SELECT ... ORDER BY ts` only if every consequential action
lands in the same table. Sub-schemas keep their operational state
(`spine_lifecycle.transition`, `spine_verify_*`); `spine_audit.audit_event`
is the single source of what happened and why.

## Schema overview

| Column | Purpose |
|---|---|
| `event_id` / `event_uuid` | Monotonic PK + stable external id. |
| `ts` | Action timestamp (TIMESTAMPTZ; primary index). |
| `project_id` | Nullable — bundle installs, daemon starts are project-less. |
| `phase`, `role`, `subsystem`, `action` | The 4-tuple that identifies what kind of event this is. `subsystem` is constrained to plan/build/verify/orchestrator/shared. |
| `subject_type`, `subject_id` | What was acted on (directive, artifact, approval, ...). |
| `actor`, `rationale` | Who did it + why. `rationale` is required for human-driven actions (enforced at the application layer). |
| `metadata` | JSONB for action payload (model, tokens, finding ids). GIN-indexed (`jsonb_path_ops`). |
| `prompt_hash` / `output_hash` | SHA-256 of LLM input/output when applicable. |
| `cost_usd` | Per-action cost; rolls into `spine_recording.costs` (FR-7). |
| `pipeline_version` | Locked manifest version at event time (FR-8 versioning). |
| `correlation_id` | Ties related events (dispatch + reply) together. |
| `parent_event_id` | Tree views (gate_check parent of approval_granted). |
| `error_code` / `error_message` | Failure rows. |
| `prev_event_hash` / `content_hash` | Chain of hashes for tamper detection. |

## Append-only enforcement

Two layers, both required:

1. **Postgres role `spine_audit_writer`** — `INSERT, SELECT` only on
   `audit_event`. `UPDATE`, `DELETE`, `TRUNCATE` are explicitly revoked from
   both `PUBLIC` and this role. Spine subsystems connect as this role.
2. **Trigger `trg_audit_event_no_update` / `trg_audit_event_no_delete`** —
   raises `insufficient_privilege` on UPDATE/DELETE regardless of role,
   including superuser. The trigger is the belt; the role is the braces.

The only legitimate removal path is `DROP TABLE spine_audit.audit_event`
during `spine uninstall --purge` — deliberately outside Flyway.

## Chain-of-hashes tamper detection

Each row stores `content_hash = SHA-256(canonical_json(row \ content_hash))`
and `prev_event_hash = content_hash of the previous row`. Bitcoin-light:
flipping a byte in row N invalidates row N's `content_hash`, which breaks
row N+1's `prev_event_hash`, and so on. The view
`v_audit_chain_integrity` returns rows where stored `prev_event_hash`
disagrees with the actual prior row — non-empty = tampered.

Hash computation lives in `shared/audit/audit_record.py`.

## Example queries

```sql
-- Chronological audit trail for one project
SELECT ts, role, action, subject_id, rationale FROM spine_audit.audit_event
WHERE project_id = $1 ORDER BY ts;

-- Reconstruct a directive's flow via correlation_id
SELECT * FROM spine_audit.audit_event WHERE correlation_id = $1 ORDER BY ts;

-- Detect chain breaks
SELECT * FROM spine_audit.v_audit_chain_integrity LIMIT 10;

-- Per-day LLM cost
SELECT date_trunc('day', ts) AS day, SUM(cost_usd) AS usd
FROM spine_audit.audit_event WHERE action = 'llm_call' GROUP BY 1 ORDER BY 1;

-- Running cost per project (uses bundled view)
SELECT ts, action, cost_usd, running_cost_usd
FROM spine_audit.v_audit_per_project WHERE project_id = $1;
```
