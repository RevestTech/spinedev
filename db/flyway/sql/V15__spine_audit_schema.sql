-- V15: Spine unified audit log (INIT-3 / EPIC-3.1, EPIC-9.7).
--
-- Implements STORY-3.1.1 (audit record schema) and STORY-3.1.2 (storage =
-- Postgres, per memory/spine_tech_stack_decisions.md). Satisfies REQ-INIT-9
-- FR-8 (append-only Postgres role; survives uninstall; queryable by
-- project_id) and feeds REQ-INIT-7 FR-3 (BuildArtifact), REQ-INIT-8 FR-4
-- (Verify findings), REQ-INIT-1 FR-5 (gate decisions).
--
-- One table for the whole product: cross-subsystem reconstruction stays
-- cheap only if every consequential action lands in the same chronological
-- table. DELETE policy: rows are NEVER updated or deleted — only legitimate
-- removal is `DROP TABLE` during clean `spine uninstall --purge`.

BEGIN;

CREATE SCHEMA IF NOT EXISTS spine_audit;
COMMENT ON SCHEMA spine_audit IS
'Unified, append-only audit log for every consequential Spine action (Plan, Build, Verify, Orchestrator).';

CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid()

-- ─────────────────────────────────────────────────────────────────────
-- audit_event — one row per consequential action.
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_audit.audit_event (
    event_id BIGSERIAL PRIMARY KEY,
    event_uuid UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    project_id BIGINT,
    phase TEXT,
    role TEXT NOT NULL,
    subsystem TEXT NOT NULL,
    action TEXT NOT NULL,
    subject_type TEXT,
    subject_id TEXT,
    actor TEXT NOT NULL,
    rationale TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    prompt_hash TEXT,
    output_hash TEXT,
    cost_usd NUMERIC(12, 6),
    pipeline_version TEXT,
    correlation_id UUID,
    parent_event_id BIGINT REFERENCES spine_audit.audit_event (event_id),
    error_code TEXT,
    error_message TEXT,
    prev_event_hash TEXT,
    content_hash TEXT NOT NULL,
    CONSTRAINT audit_event_subsystem_chk CHECK (
        subsystem IN ('plan', 'build', 'verify', 'orchestrator', 'shared')
    ),
    CONSTRAINT audit_event_cost_nonneg_chk CHECK (
        cost_usd IS NULL OR cost_usd >= 0
    ),
    CONSTRAINT audit_event_hashlen_chk CHECK (char_length(content_hash) = 64)
);

COMMENT ON TABLE spine_audit.audit_event IS 'Append-only ledger: every consequential action across all Spine subsystems.';
COMMENT ON COLUMN spine_audit.audit_event.event_id IS 'Surrogate PK; monotonic, stable ordering.';
COMMENT ON COLUMN spine_audit.audit_event.event_uuid IS 'External-facing stable id (URLs, exports, cross-system references).';
COMMENT ON COLUMN spine_audit.audit_event.project_id IS 'spine_lifecycle.project.id (nullable; some events are project-less, e.g., bundle install).';
COMMENT ON COLUMN spine_audit.audit_event.phase IS 'SDLC phase at the moment of the action; nullable for project-less events.';
COMMENT ON COLUMN spine_audit.audit_event.role IS 'Spine role that acted: engineer, architect, planner, qa, conductor, system, ...';
COMMENT ON COLUMN spine_audit.audit_event.subsystem IS 'plan | build | verify | orchestrator | shared.';
COMMENT ON COLUMN spine_audit.audit_event.action IS 'Event type: directive_dispatched, phase_advanced, approval_granted, llm_call, gate_check, subsystem_registered, budget_blocked, ...';
COMMENT ON COLUMN spine_audit.audit_event.subject_type IS 'What kind of thing was acted on: directive, artifact, project, approval, pipeline_manifest, ...';
COMMENT ON COLUMN spine_audit.audit_event.subject_id IS 'Identifier (path/uuid/id) of the acted-on thing.';
COMMENT ON COLUMN spine_audit.audit_event.actor IS 'User handle or system principal that performed the action.';
COMMENT ON COLUMN spine_audit.audit_event.rationale IS 'Free-text justification. REQUIRED for human-driven actions (enforced at the application layer, not SQL).';
COMMENT ON COLUMN spine_audit.audit_event.metadata IS 'Action-specific structured data (model name, token counts, finding ids, etc.).';
COMMENT ON COLUMN spine_audit.audit_event.prompt_hash IS 'SHA-256 of the prompt sent to the LLM, when applicable.';
COMMENT ON COLUMN spine_audit.audit_event.output_hash IS 'SHA-256 of the LLM output, when applicable.';
COMMENT ON COLUMN spine_audit.audit_event.cost_usd IS 'USD cost of this action; rolls up to spine_recording.costs (REQ-INIT-9 FR-7).';
COMMENT ON COLUMN spine_audit.audit_event.pipeline_version IS 'Locked pipeline manifest version active when the event occurred (REQ-INIT-1 FR-8).';
COMMENT ON COLUMN spine_audit.audit_event.correlation_id IS 'Ties related events together (a dispatch + its reply share this UUID).';
COMMENT ON COLUMN spine_audit.audit_event.parent_event_id IS 'Tree-of-events parent (e.g., gate_check parent of approval_granted).';
COMMENT ON COLUMN spine_audit.audit_event.error_code IS 'Set if this row represents a failure (timeout, budget_exceeded, ...).';
COMMENT ON COLUMN spine_audit.audit_event.prev_event_hash IS 'content_hash of the previous event in chain order; tamper-detection (see V15 README).';
COMMENT ON COLUMN spine_audit.audit_event.content_hash IS 'SHA-256 of this event canonicalised (excluding content_hash itself).';

-- ─────────────────────────────────────────────────────────────────────
-- Indexes — chronological is the primary access pattern; per-project,
-- correlation, and subsystem/action filters are the next tier.
-- ─────────────────────────────────────────────────────────────────────

CREATE INDEX idx_audit_event_ts ON spine_audit.audit_event (ts DESC);
CREATE INDEX idx_audit_event_project_ts ON spine_audit.audit_event (project_id, ts DESC);
CREATE INDEX idx_audit_event_correlation ON spine_audit.audit_event (correlation_id) WHERE correlation_id IS NOT NULL;
CREATE INDEX idx_audit_event_subsystem_action ON spine_audit.audit_event (subsystem, action, ts DESC);
CREATE INDEX idx_audit_event_metadata_gin ON spine_audit.audit_event USING gin (metadata jsonb_path_ops);

-- ─────────────────────────────────────────────────────────────────────
-- Append-only enforcement. Defence in depth: dedicated INSERT-only role
-- (braces) + trigger that raises on UPDATE/DELETE for everyone (belt).
-- ─────────────────────────────────────────────────────────────────────

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'spine_audit_writer') THEN
        CREATE ROLE spine_audit_writer NOLOGIN;
    END IF;
END$$;

REVOKE ALL ON spine_audit.audit_event FROM public;
REVOKE UPDATE, DELETE, TRUNCATE ON spine_audit.audit_event FROM public;
GRANT USAGE ON SCHEMA spine_audit TO spine_audit_writer;
GRANT INSERT, SELECT ON spine_audit.audit_event TO spine_audit_writer;
GRANT USAGE, SELECT ON SEQUENCE spine_audit.audit_event_event_id_seq TO spine_audit_writer;
-- Explicitly refuse mutation privileges.
REVOKE UPDATE, DELETE, TRUNCATE ON spine_audit.audit_event FROM spine_audit_writer;

CREATE OR REPLACE FUNCTION spine_audit.reject_mutation() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'spine_audit.audit_event is append-only; % is not permitted', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_audit_event_no_update
BEFORE UPDATE ON spine_audit.audit_event
FOR EACH ROW EXECUTE FUNCTION spine_audit.reject_mutation();

CREATE TRIGGER trg_audit_event_no_delete
BEFORE DELETE ON spine_audit.audit_event
FOR EACH ROW EXECUTE FUNCTION spine_audit.reject_mutation();

COMMENT ON FUNCTION spine_audit.reject_mutation() IS
'Refuses UPDATE/DELETE on audit_event even for superusers. Only DROP TABLE during clean uninstall removes rows.';

-- ─────────────────────────────────────────────────────────────────────
-- Views (P1 in REQ-INIT-9 FR-8; included now — both are one-liners).
-- ─────────────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW spine_audit.v_audit_per_project AS
SELECT
    e.project_id,
    e.ts,
    e.phase,
    e.subsystem,
    e.role,
    e.action,
    e.subject_type,
    e.subject_id,
    e.actor,
    e.rationale,
    e.cost_usd,
    sum(coalesce(e.cost_usd, 0)) OVER (
        PARTITION BY e.project_id ORDER BY e.ts, e.event_id
    ) AS running_cost_usd,
    e.event_uuid,
    e.correlation_id
FROM spine_audit.audit_event AS e
ORDER BY e.project_id, e.ts, e.event_id;

COMMENT ON VIEW spine_audit.v_audit_per_project IS
'Chronological audit trail per project with running-cost window.';

CREATE OR REPLACE VIEW spine_audit.v_audit_chain_integrity AS
WITH chained AS (
    SELECT
        event_id,
        event_uuid,
        ts,
        prev_event_hash,
        content_hash,
        lag(content_hash) OVER (ORDER BY event_id) AS expected_prev_hash
    FROM spine_audit.audit_event
)

SELECT
    event_id,
    event_uuid,
    ts,
    prev_event_hash,
    expected_prev_hash,
    content_hash
FROM chained
WHERE
    event_id > 1
    AND (prev_event_hash IS DISTINCT FROM expected_prev_hash);

COMMENT ON VIEW spine_audit.v_audit_chain_integrity IS
'Returns audit_event rows whose prev_event_hash does NOT match the prior rows content_hash (tamper indicator).';

COMMIT;
