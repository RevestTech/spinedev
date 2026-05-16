-- V3: Spine Orchestrator lifecycle schema (INIT-9 / EPIC-9.1).
--
-- Implements STORY-9.1.1: Postgres `spine_lifecycle` schema holding the
-- canonical state of every project moving through the SDLC pipeline.
--
-- Architectural placement (docs/ARCHITECTURE.md §3 R-2): one Postgres
-- instance, multi-schema. This migration creates `spine_lifecycle` alongside
-- the existing `public` (recording), and the future `spine_kg`,
-- `spine_audit`, `spine_verify_*` schemas. Cross-schema joins are allowed;
-- per-schema ownership keeps the surface area inspectable.
--
-- The canonical phase set is data, not code: it lives in
-- `orchestrator/state/phases.yaml` (STORY-9.1.3) and is editable per
-- org-bundle (STORY-9.1.4 / EPIC-1.7). The schema below stores phases as
-- free-text `TEXT` so org overrides do not require a migration; the
-- transition engine (STORY-9.2.1) validates `(from_phase, to_phase)` pairs
-- against the pipeline manifest pinned to each project at creation time
-- (`project.pipeline_version`, STORY-1.7.5).
--
-- NOTE on version collision: `V3__multi_host.sql` already exists in this
-- repo at the time of authoring. This file is being submitted under the
-- name requested by the task spec (`V3__spine_lifecycle_schema.sql`); the
-- integrator should renumber to the next free slot (currently V14) before
-- running `make migrate`.

BEGIN;

-- ─────────────────────────────────────────────────────────────────────
-- Schema
-- ─────────────────────────────────────────────────────────────────────

CREATE SCHEMA IF NOT EXISTS spine_lifecycle;
COMMENT ON SCHEMA spine_lifecycle IS
  'Orchestrator (INIT-9) state: projects, phase history, transitions, approvals, route dispatches.';

-- pgcrypto is created in V1 for the recording schema; ensure it is present
-- so gen_random_uuid() resolves under search_path = spine_lifecycle too.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Reuse the shared updated_at trigger function from V1 (public.set_updated_at).
-- If the integrator renumbers this file ahead of V1 it must add a local copy.

-- ─────────────────────────────────────────────────────────────────────
-- project — one row per Spine project under orchestration.
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_lifecycle.project (
    id                      BIGSERIAL    PRIMARY KEY,
    project_uuid            UUID         NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    name                    TEXT         NOT NULL,
    project_type            TEXT         NOT NULL,
    current_phase           TEXT         NOT NULL DEFAULT 'intake',
    pipeline_version        TEXT         NOT NULL,
    pipeline_manifest_path  TEXT         NOT NULL,
    org_bundle              TEXT,
    team_id                 TEXT,
    owner_user              TEXT         NOT NULL,
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    status                  TEXT         NOT NULL DEFAULT 'active',
    metadata                JSONB        NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT project_status_chk CHECK (status IN ('active','paused','terminated','completed'))
);

COMMENT ON TABLE  spine_lifecycle.project                          IS 'One row per project under orchestrator management.';
COMMENT ON COLUMN spine_lifecycle.project.id                       IS 'Surrogate PK used by all child tables.';
COMMENT ON COLUMN spine_lifecycle.project.project_uuid             IS 'External-facing stable identifier (URLs, API).';
COMMENT ON COLUMN spine_lifecycle.project.name                     IS 'Human label.';
COMMENT ON COLUMN spine_lifecycle.project.project_type             IS 'web_app | internal_tool | data_pipeline | ... (drives swarm composition, EPIC-1.2).';
COMMENT ON COLUMN spine_lifecycle.project.current_phase            IS 'Denormalised cache of the most recent phase_history row (cheap reads).';
COMMENT ON COLUMN spine_lifecycle.project.pipeline_version         IS 'Locked pipeline version at project start (EPIC-1.7.5); immutable for the life of the project.';
COMMENT ON COLUMN spine_lifecycle.project.pipeline_manifest_path   IS 'Path or content-hash of the sdlc-pipeline.yaml manifest this project locked to.';
COMMENT ON COLUMN spine_lifecycle.project.org_bundle               IS 'Which org bundle (overlay) is in effect; NULL = stock Spine defaults.';
COMMENT ON COLUMN spine_lifecycle.project.team_id                  IS 'Foreign key (text) into spine_recording.team for cost rollups; nullable for orphan projects.';
COMMENT ON COLUMN spine_lifecycle.project.owner_user               IS 'User who created/owns the project.';
COMMENT ON COLUMN spine_lifecycle.project.status                   IS 'active | paused | terminated | completed (lifecycle envelope around phase).';
COMMENT ON COLUMN spine_lifecycle.project.metadata                 IS 'Free-form JSON (custom tags, links, integrations).';

CREATE INDEX idx_project_status_phase     ON spine_lifecycle.project (status, current_phase);
CREATE INDEX idx_project_owner            ON spine_lifecycle.project (owner_user);
CREATE INDEX idx_project_team             ON spine_lifecycle.project (team_id);

CREATE TRIGGER trg_project_updated_at
    BEFORE UPDATE ON spine_lifecycle.project
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ─────────────────────────────────────────────────────────────────────
-- phase_history — append-only log of every (project, phase) the project
-- has occupied. `exited_at` NULL means currently in this phase.
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_lifecycle.phase_history (
    id            BIGSERIAL    PRIMARY KEY,
    project_id    BIGINT       NOT NULL REFERENCES spine_lifecycle.project(id) ON DELETE CASCADE,
    phase         TEXT         NOT NULL,
    entered_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    exited_at     TIMESTAMPTZ,
    outcome       TEXT,
    artifact_ref  TEXT,
    CONSTRAINT phase_history_outcome_chk CHECK (
        outcome IS NULL OR outcome IN ('advanced','rejected','request_changes','rolled_back')
    )
);

COMMENT ON TABLE  spine_lifecycle.phase_history              IS 'Every (project, phase) the project has occupied; one row per phase visit.';
COMMENT ON COLUMN spine_lifecycle.phase_history.phase        IS 'Phase id (matches phases.yaml). Free text — org bundles may extend.';
COMMENT ON COLUMN spine_lifecycle.phase_history.entered_at   IS 'When the project entered this phase.';
COMMENT ON COLUMN spine_lifecycle.phase_history.exited_at    IS 'When it left; NULL = still here.';
COMMENT ON COLUMN spine_lifecycle.phase_history.outcome      IS 'How the phase concluded: advanced | rejected | request_changes | rolled_back.';
COMMENT ON COLUMN spine_lifecycle.phase_history.artifact_ref IS 'Reference (path / id) to the artifact this phase produced.';

CREATE INDEX idx_phase_history_project_entered ON spine_lifecycle.phase_history (project_id, entered_at DESC);
CREATE INDEX idx_phase_history_phase_open      ON spine_lifecycle.phase_history (phase) WHERE exited_at IS NULL;

-- ─────────────────────────────────────────────────────────────────────
-- transition — every state transition attempted, success OR rejection
-- (STORY-9.2.1, STORY-9.2.2). Also the primary audit feed for EPIC-9.7.
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_lifecycle.transition (
    id          BIGSERIAL    PRIMARY KEY,
    project_id  BIGINT       NOT NULL REFERENCES spine_lifecycle.project(id) ON DELETE CASCADE,
    from_phase  TEXT         NOT NULL,
    to_phase    TEXT         NOT NULL,
    at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    actor       TEXT         NOT NULL,
    decision    TEXT         NOT NULL,
    reason      TEXT,
    metadata    JSONB        NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT transition_decision_chk CHECK (
        decision IN ('allowed','rejected_invalid','rejected_gate','rejected_capability')
    )
);

COMMENT ON TABLE  spine_lifecycle.transition           IS 'Every attempted phase transition (allowed or rejected). Append-only.';
COMMENT ON COLUMN spine_lifecycle.transition.actor     IS 'Username, role handle, or system principal that initiated the transition.';
COMMENT ON COLUMN spine_lifecycle.transition.decision  IS 'Outcome of the validation engine.';
COMMENT ON COLUMN spine_lifecycle.transition.reason    IS 'Human/machine explanation when rejected.';
COMMENT ON COLUMN spine_lifecycle.transition.metadata  IS 'Free-form JSON (e.g., approval token id, rollback rationale).';

CREATE INDEX idx_transition_project_at  ON spine_lifecycle.transition (project_id, at DESC);
CREATE INDEX idx_transition_decision_at ON spine_lifecycle.transition (decision, at DESC);

-- ─────────────────────────────────────────────────────────────────────
-- approval — phase-gate approval tokens (EPIC-9.3 / STORY-9.3.2).
-- HMAC-signed tokens permit cryptographic verification on advance.
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_lifecycle.approval (
    id            BIGSERIAL    PRIMARY KEY,
    project_id    BIGINT       NOT NULL REFERENCES spine_lifecycle.project(id) ON DELETE CASCADE,
    phase         TEXT         NOT NULL,
    artifact_ref  TEXT         NOT NULL,
    approver      TEXT         NOT NULL,
    decision      TEXT         NOT NULL,
    notes         TEXT,
    token         TEXT,
    granted_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    expires_at    TIMESTAMPTZ,
    CONSTRAINT approval_decision_chk CHECK (
        decision IN ('approved','rejected','request_changes')
    )
);

COMMENT ON TABLE  spine_lifecycle.approval              IS 'Phase-gate approval records. Multiple rows per (project, phase) when multi-approver (STORY-9.3.3).';
COMMENT ON COLUMN spine_lifecycle.approval.artifact_ref IS 'Reference to the artifact under review (PRD, build_artifact, verify_findings, ...).';
COMMENT ON COLUMN spine_lifecycle.approval.approver     IS 'User or role handle of the approver.';
COMMENT ON COLUMN spine_lifecycle.approval.token        IS 'HMAC-signed opaque token; transition engine verifies before allowing advance.';
COMMENT ON COLUMN spine_lifecycle.approval.expires_at   IS 'Optional expiry; expired approvals do not unlock the gate.';

CREATE INDEX idx_approval_project_phase_decision ON spine_lifecycle.approval (project_id, phase, decision);
CREATE INDEX idx_approval_expires_at             ON spine_lifecycle.approval (expires_at) WHERE expires_at IS NOT NULL;

-- ─────────────────────────────────────────────────────────────────────
-- route_history — every directive dispatch the orchestrator made
-- (STORY-9.4.1 / STORY-9.4.3). Pairs dispatched_at/completed_at.
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_lifecycle.route_history (
    id             BIGSERIAL     PRIMARY KEY,
    project_id     BIGINT        NOT NULL REFERENCES spine_lifecycle.project(id) ON DELETE CASCADE,
    phase          TEXT          NOT NULL,
    subsystem      TEXT          NOT NULL,
    role           TEXT          NOT NULL,
    directive_ref  TEXT          NOT NULL,
    dispatched_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    completed_at   TIMESTAMPTZ,
    outcome        TEXT,
    cost           NUMERIC(10,4),
    metadata       JSONB         NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT route_history_subsystem_chk CHECK (subsystem IN ('plan','build','verify')),
    CONSTRAINT route_history_outcome_chk   CHECK (
        outcome IS NULL OR outcome IN ('completed','failed','timeout','retry')
    )
);

COMMENT ON TABLE  spine_lifecycle.route_history               IS 'Every directive the orchestrator dispatched to a subsystem.';
COMMENT ON COLUMN spine_lifecycle.route_history.subsystem     IS 'plan | build | verify (corresponds to the three SDLC subsystems).';
COMMENT ON COLUMN spine_lifecycle.route_history.role          IS 'Role handle the directive targeted (engineer-backend, qa, ...).';
COMMENT ON COLUMN spine_lifecycle.route_history.directive_ref IS 'Path/id of the directive artifact handed to the subsystem.';
COMMENT ON COLUMN spine_lifecycle.route_history.cost          IS 'USD cost reported back by the subsystem on completion.';

CREATE INDEX idx_route_history_project_dispatched ON spine_lifecycle.route_history (project_id, dispatched_at DESC);
CREATE INDEX idx_route_history_subsystem_role     ON spine_lifecycle.route_history (subsystem, role, dispatched_at DESC);
CREATE INDEX idx_route_history_open               ON spine_lifecycle.route_history (project_id) WHERE completed_at IS NULL;

-- ─────────────────────────────────────────────────────────────────────
-- portfolio_view — cross-project per-phase rollup (STORY-9.5.3).
-- Counts only ACTIVE projects. Cheap because of idx_project_status_phase.
-- ─────────────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW spine_lifecycle.portfolio_view AS
SELECT
    current_phase                                AS phase,
    COUNT(*)                                     AS project_count,
    MIN(updated_at)                              AS oldest_in_phase,
    MAX(updated_at)                              AS newest_in_phase,
    ARRAY_AGG(project_uuid ORDER BY updated_at)  AS project_uuids
FROM   spine_lifecycle.project
WHERE  status = 'active'
GROUP  BY current_phase
ORDER  BY current_phase;

COMMENT ON VIEW spine_lifecycle.portfolio_view IS
  'Active projects rolled up by current phase; the orchestrator dashboard reads this for the portfolio card.';

COMMIT;
