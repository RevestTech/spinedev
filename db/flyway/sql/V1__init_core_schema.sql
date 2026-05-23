-- V1: Spine core schema (Postgres 16 port of .planning/orchestration/schema/v2.sql).
--
-- Ports the SQLite v2 draft to Postgres 16:
--   * Surrogate keys: UUID with `gen_random_uuid()` (from pgcrypto). Lookup
--     tables keep their text natural keys ('low', 'engineer', ...).
--   * Timestamps: TIMESTAMPTZ DEFAULT now().
--   * JSON columns: JSONB DEFAULT '{}'::jsonb.
--   * Closed status sets are real ENUM types where they buy us safety.
--   * "One active assignment per worker" is enforced by a partial unique index.
--   * `updated_at` is maintained by a shared trigger function on hot tables.
--
-- This migration creates the 19 core tables (counting lookups, the total is 23).

-- ─────────────────────────────────────────────────────────────────────
-- Extensions
-- ─────────────────────────────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ─────────────────────────────────────────────────────────────────────
-- Enum types
-- ─────────────────────────────────────────────────────────────────────

CREATE TYPE worker_status AS ENUM ('active', 'idle', 'stopped');
CREATE TYPE task_status AS ENUM (
    'open', 'in_progress', 'blocked', 'done', 'cancelled'
);
CREATE TYPE assignment_status AS ENUM ('active', 'done', 'abandoned', 'failed');
CREATE TYPE review_status AS ENUM (
    'pending', 'approved', 'rejected', 'changes_requested'
);
CREATE TYPE artifact_kind AS ENUM (
    'pr', 'file', 'test_report', 'deploy', 'memo', 'other'
);

-- ─────────────────────────────────────────────────────────────────────
-- Shared trigger function: maintain updated_at on UPDATE.
-- ─────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ─────────────────────────────────────────────────────────────────────
-- Lookups (small, mostly read-only; text natural keys)
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE job_family (
    family_id text PRIMARY KEY,                       -- e.g., 'engineer'
    name text NOT NULL UNIQUE
);

CREATE TABLE discipline (
    discipline_id text PRIMARY KEY,                     -- e.g., 'backend'
    name text NOT NULL UNIQUE
);

CREATE TABLE level (
    level_id text PRIMARY KEY,                         -- e.g., 'senior'
    name text NOT NULL UNIQUE,
    rank integer NOT NULL                          -- 1=junior, 2=mid, ...
);

CREATE TABLE tier (
    tier_id text PRIMARY KEY,                          -- 'low' | 'med' | 'high'
    name text NOT NULL UNIQUE
);

CREATE TABLE provider (
    -- 'openai', 'anthropic', ...
    provider_id text PRIMARY KEY,
    name text NOT NULL UNIQUE
);

CREATE TABLE model (
    model_id text PRIMARY KEY,
    provider_id text NOT NULL REFERENCES provider (provider_id),
    name text NOT NULL,
    context_tokens integer,
    cost_in_usd_per_1k_tokens numeric(12, 6) NOT NULL,
    cost_out_usd_per_1k_tokens numeric(12, 6) NOT NULL,
    default_tier_id text REFERENCES tier (tier_id),
    archived_at timestamptz,
    UNIQUE (provider_id, name)
);

CREATE TABLE role (
    role_id text PRIMARY KEY,                   -- 'engineer-backend', ...
    name text NOT NULL UNIQUE,
    family_id text NOT NULL REFERENCES job_family (family_id),
    level_id text REFERENCES level (level_id),
    discipline_id text REFERENCES discipline (discipline_id),
    default_tier_id text REFERENCES tier (tier_id),
    CHECK (discipline_id IS NULL OR family_id = 'engineer')
);

-- ─────────────────────────────────────────────────────────────────────
-- Org structure
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE team (
    team_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    archived_at timestamptz
);

CREATE TABLE worker (
    worker_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id uuid NOT NULL REFERENCES team (team_id),
    role_id text NOT NULL REFERENCES role (role_id),
    parent_worker_id uuid REFERENCES worker (worker_id),
    handle text NOT NULL,
    display_name text,
    status worker_status NOT NULL DEFAULT 'idle',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    archived_at timestamptz,
    UNIQUE (team_id, handle)
);
CREATE INDEX idx_worker_team ON worker (team_id);
CREATE INDEX idx_worker_role ON worker (role_id);
CREATE INDEX idx_worker_parent ON worker (parent_worker_id);
CREATE INDEX idx_worker_active ON worker (team_id) WHERE archived_at IS NULL;

CREATE TRIGGER worker_set_updated_at
BEFORE UPDATE ON worker
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ─────────────────────────────────────────────────────────────────────
-- Tasks & assignments (the work-product loop)
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE task (
    task_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id uuid NOT NULL REFERENCES team (team_id),
    external_ref text,
    title text NOT NULL,
    description text,
    status task_status NOT NULL DEFAULT 'open',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    closed_at timestamptz
);
CREATE INDEX idx_task_team_status ON task (team_id, status);

CREATE TRIGGER task_set_updated_at
BEFORE UPDATE ON task
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE prompt (
    prompt_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    role_id text NOT NULL REFERENCES role (role_id),
    name text NOT NULL,
    UNIQUE (role_id, name)
);

CREATE TABLE prompt_version (
    prompt_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_id uuid NOT NULL REFERENCES prompt (prompt_id),
    version integer NOT NULL,
    template text NOT NULL,
    variables_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (prompt_id, version)
);

CREATE TABLE assignment (
    assignment_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    worker_id uuid NOT NULL REFERENCES worker (worker_id),
    task_id uuid REFERENCES task (task_id),
    parent_assignment_id uuid REFERENCES assignment (assignment_id),
    prompt_version_id uuid REFERENCES prompt_version (prompt_version_id),
    task_ref text,
    started_at timestamptz NOT NULL DEFAULT now(),
    ended_at timestamptz,
    status assignment_status NOT NULL DEFAULT 'active',
    idempotency_key text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (worker_id, idempotency_key)
);
CREATE INDEX idx_assignment_worker ON assignment (worker_id);
CREATE INDEX idx_assignment_task ON assignment (task_id);
CREATE INDEX idx_assignment_parent ON assignment (parent_assignment_id);
CREATE INDEX idx_assignment_status ON assignment (status);
CREATE INDEX idx_assignment_active ON assignment (worker_id) WHERE status
= 'active';

-- "One active assignment per worker" — enforced at the DB level (was app-level
-- in the SQLite draft).
CREATE UNIQUE INDEX assignment_one_active_per_worker
ON assignment (worker_id)
WHERE status = 'active';

CREATE TRIGGER assignment_set_updated_at
BEFORE UPDATE ON assignment
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Directive — 1:1 with an *active* Assignment.
CREATE TABLE directive (
    assignment_id uuid PRIMARY KEY REFERENCES assignment (
        assignment_id
    ) ON DELETE CASCADE,
    header text NOT NULL,
    body_md_uri text,
    body_md_hash text,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER directive_set_updated_at
BEFORE UPDATE ON directive
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Report — 1:1 with a *closed* Assignment.
CREATE TABLE report (
    assignment_id uuid PRIMARY KEY REFERENCES assignment (
        assignment_id
    ) ON DELETE CASCADE,
    header text,
    body_md_uri text,
    body_md_hash text,
    finished_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER report_set_updated_at
BEFORE UPDATE ON report
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Artifact — outputs produced by an assignment (PR, file, test report, ...).
CREATE TABLE artifact (
    artifact_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    assignment_id uuid NOT NULL REFERENCES assignment (
        assignment_id
    ) ON DELETE CASCADE,
    kind artifact_kind NOT NULL,
    uri text NOT NULL,
    title text,
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_artifact_assignment ON artifact (assignment_id);
CREATE INDEX idx_artifact_kind ON artifact (kind);

-- Review — closes the loop between a worker and its parent/reviewer.
CREATE TABLE review (
    review_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    assignment_id uuid NOT NULL REFERENCES assignment (
        assignment_id
    ) ON DELETE CASCADE,
    reviewer_worker_id uuid NOT NULL REFERENCES worker (worker_id),
    status review_status NOT NULL DEFAULT 'pending',
    comment text,
    requested_at timestamptz NOT NULL DEFAULT now(),
    reviewed_at timestamptz
);
CREATE INDEX idx_review_assignment ON review (assignment_id);
CREATE INDEX idx_review_reviewer ON review (reviewer_worker_id);
CREATE INDEX idx_review_pending ON review (status) WHERE status = 'pending';

-- Handoff — "engineer-alpha -> qa-alpha" event records.
CREATE TABLE handoff (
    handoff_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    from_worker_id uuid NOT NULL REFERENCES worker (worker_id),
    to_worker_id uuid NOT NULL REFERENCES worker (worker_id),
    assignment_id uuid REFERENCES assignment (assignment_id),
    payload_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_handoff_to ON handoff (to_worker_id, created_at);

-- ─────────────────────────────────────────────────────────────────────
-- Cost & budget
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE cost_row (
    assignment_id uuid NOT NULL REFERENCES assignment (
        assignment_id
    ) ON DELETE CASCADE,
    ts timestamptz NOT NULL DEFAULT now(),
    model_id text REFERENCES model (model_id),
    tier_id text REFERENCES tier (tier_id),
    -- 'plan' | 'apply' | 'review' | ...
    mode text,
    phase text,
    tokens_in integer NOT NULL DEFAULT 0,
    tokens_out integer NOT NULL DEFAULT 0,
    wall_s double precision NOT NULL DEFAULT 0,
    cost_usd numeric(14, 6) NOT NULL DEFAULT 0,
    rc integer,
    PRIMARY KEY (assignment_id, ts)
);
CREATE INDEX idx_cost_row_ts ON cost_row (ts);
CREATE INDEX idx_cost_row_model ON cost_row (model_id);

-- ─────────────────────────────────────────────────────────────────────
-- Memory
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE team_memory (
    team_id uuid PRIMARY KEY REFERENCES team (team_id) ON DELETE CASCADE,
    corpus_uri text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE worker_memory (
    worker_id uuid PRIMARY KEY REFERENCES worker (worker_id) ON DELETE CASCADE,
    corpus_uri text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────────────
-- Rollback (worker-scoped; mirrors v1 CSV semantics)
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE rollback_entry (
    worker_id uuid NOT NULL REFERENCES worker (worker_id) ON DELETE CASCADE,
    ts timestamptz NOT NULL DEFAULT now(),
    -- 'commit' | 'file_write' | 'deploy'
    action text NOT NULL,
    target text NOT NULL,
    sha text,
    PRIMARY KEY (worker_id, ts)
);

-- ─────────────────────────────────────────────────────────────────────
-- Event log (append-only audit trail)
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE event (
    event_id bigserial PRIMARY KEY,
    ts timestamptz NOT NULL DEFAULT now(),
    type text NOT NULL,                        -- 'WorkerStarted', ...
    team_id uuid REFERENCES team (team_id),
    worker_id uuid REFERENCES worker (worker_id),
    assignment_id uuid REFERENCES assignment (assignment_id),
    payload_json jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX idx_event_ts ON event (ts);
CREATE INDEX idx_event_worker_ts ON event (worker_id, ts);
CREATE INDEX idx_event_assignment_ts ON event (assignment_id, ts);

-- cost_row already has PRIMARY KEY (assignment_id, ts) — that doubles as the
-- UPSERT-friendly unique index. No further index needed.
