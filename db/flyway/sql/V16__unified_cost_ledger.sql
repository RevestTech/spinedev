-- V16: Unified cost ledger — aggregate + rollup views (INIT-9 / EPIC-9.6).
--
-- STORY-9.6.1: Plan/Build/Verify/Orchestrator cost rows aggregate into a
-- single ledger keyed by `subsystem`. STORY-9.6.2: per-phase / per-project
-- / per-user / per-org rollup views. STORY-9.6.3: budget enforcement reads
-- the aggregated ledger (consumed by EPIC-2.3 via
-- `shared/cost/budget_rollup.sh check-budget`).
--
-- Maps to docs/PRD.md REQ-INIT-9 FR-7 and the cost-aware tier router in
-- REQ-INIT-1 FR-6.
--
-- Forward-only: the ALTER that adds `subsystem` has no rollback path; rows
-- written before this migration default to 'unknown'. Backfill from legacy
-- public.cost_row is a separate one-time data migration (see README).

BEGIN;

-- Schema + canonical table. The PRD names `spine_recording.costs`; V1
-- shipped legacy `public.cost_row`. This migration establishes the
-- canonical name without touching V1 (per the no-edit constraint). IF NOT
-- EXISTS keeps it idempotent if a future migration relocates cost_row.

CREATE SCHEMA IF NOT EXISTS spine_recording;
COMMENT ON SCHEMA spine_recording IS
  'Unified recording: cost ledger, telemetry, and reporting feeds across all Spine subsystems.';

CREATE TABLE IF NOT EXISTS spine_recording.costs (
    id                BIGSERIAL    PRIMARY KEY,
    ts                TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    project_id        BIGINT,
    phase             TEXT,
    actor             TEXT,
    pipeline_version  TEXT,
    model_id          TEXT,
    tier_id           TEXT,
    tokens_in         INTEGER      NOT NULL DEFAULT 0,
    tokens_out        INTEGER      NOT NULL DEFAULT 0,
    wall_s            DOUBLE PRECISION NOT NULL DEFAULT 0,
    cost_usd          NUMERIC(14,6) NOT NULL DEFAULT 0,
    metadata          JSONB        NOT NULL DEFAULT '{}'::jsonb
);

COMMENT ON TABLE spine_recording.costs IS
  'Unified cost ledger: every Plan/Build/Verify/Orchestrator LLM call lands here (REQ-INIT-9 FR-7).';

-- subsystem — discriminator that makes per-subsystem rollups possible.
-- NOT NULL with DEFAULT 'unknown' so pre-migration rows survive without
-- backfill (STORY-9.6.1 acceptance).
ALTER TABLE spine_recording.costs
    ADD COLUMN IF NOT EXISTS subsystem TEXT NOT NULL DEFAULT 'unknown';

ALTER TABLE spine_recording.costs
    DROP CONSTRAINT IF EXISTS costs_subsystem_chk;
ALTER TABLE spine_recording.costs
    ADD  CONSTRAINT costs_subsystem_chk CHECK (
        subsystem IN ('plan', 'build', 'verify', 'orchestrator', 'shared', 'unknown')
    );

COMMENT ON COLUMN spine_recording.costs.subsystem IS
  'Which Spine subsystem produced this cost row: plan|build|verify|orchestrator|shared|unknown.';

CREATE INDEX IF NOT EXISTS idx_costs_subsystem_ts
    ON spine_recording.costs (subsystem, ts DESC);
CREATE INDEX IF NOT EXISTS idx_costs_project_ts
    ON spine_recording.costs (project_id, ts DESC);

-- View 1 — per project_id × phase × subsystem. Primary input to the budget
-- enforcer (STORY-9.6.3) and the dashboard's per-project cost card.
CREATE OR REPLACE VIEW spine_recording.v_cost_per_project AS
SELECT
    project_id,
    phase,
    subsystem,
    SUM(cost_usd)::numeric  AS total_cost,
    COUNT(*)::bigint        AS event_count,
    SUM(tokens_in)::bigint  AS tokens_in_total,
    SUM(tokens_out)::bigint AS tokens_out_total,
    MIN(ts)                 AS first_event,
    MAX(ts)                 AS last_event
FROM   spine_recording.costs
GROUP  BY project_id, phase, subsystem;

COMMENT ON VIEW spine_recording.v_cost_per_project IS
  'Per project_id x phase x subsystem rollup. Consumers: budget enforcer (EPIC-2.3), dashboard, finance export.';

-- View 2 — per actor (user) with day/week/month buckets. Drives per-user
-- spend caps (STORY-2.3.1) and the user cost meter.
CREATE OR REPLACE VIEW spine_recording.v_cost_per_user AS
SELECT
    actor                            AS user_id,
    subsystem,
    date_trunc('day',   ts)::date    AS day_bucket,
    date_trunc('week',  ts)::date    AS week_bucket,
    date_trunc('month', ts)::date    AS month_bucket,
    SUM(cost_usd)::numeric           AS total_cost,
    COUNT(*)::bigint                 AS event_count,
    MIN(ts)                          AS first_event,
    MAX(ts)                          AS last_event
FROM   spine_recording.costs
WHERE  actor IS NOT NULL
GROUP  BY actor, subsystem,
          date_trunc('day',   ts),
          date_trunc('week',  ts),
          date_trunc('month', ts);

COMMENT ON VIEW spine_recording.v_cost_per_user IS
  'Per-user spend by subsystem with day/week/month buckets. Consumers: per-user budget enforcer (EPIC-2.3), user cost meter.';

-- View 3 — per org (org_id read via project.org_bundle join). Drives
-- org-wide spend caps and finance export.
CREATE OR REPLACE VIEW spine_recording.v_cost_per_org AS
SELECT
    p.org_bundle              AS org_id,
    c.subsystem,
    c.phase,
    SUM(c.cost_usd)::numeric  AS total_cost,
    COUNT(*)::bigint          AS event_count,
    MIN(c.ts)                 AS first_event,
    MAX(c.ts)                 AS last_event
FROM   spine_recording.costs    AS c
JOIN   spine_lifecycle.project  AS p ON p.id = c.project_id
GROUP  BY p.org_bundle, c.subsystem, c.phase;

COMMENT ON VIEW spine_recording.v_cost_per_org IS
  'Per-org rollup via project.org_bundle join. Consumers: org-wide budget enforcer (EPIC-2.3), finance export, multi-tenant billing.';

-- View 4 — per pipeline_version. Lets the architect see whether a manifest
-- change (EPIC-1.7) moved per-project cost up or down.
CREATE OR REPLACE VIEW spine_recording.v_cost_per_pipeline_version AS
SELECT
    pipeline_version,
    subsystem,
    phase,
    COUNT(DISTINCT project_id)::bigint AS project_count,
    SUM(cost_usd)::numeric             AS total_cost,
    AVG(cost_usd)::numeric             AS avg_cost_per_event,
    COUNT(*)::bigint                   AS event_count,
    MIN(ts)                            AS first_event,
    MAX(ts)                            AS last_event
FROM   spine_recording.costs
WHERE  pipeline_version IS NOT NULL
GROUP  BY pipeline_version, subsystem, phase;

COMMENT ON VIEW spine_recording.v_cost_per_pipeline_version IS
  'Per-pipeline-version cost-impact rollup. Consumers: architect reviewing manifest changes (EPIC-1.7), regression dashboard.';

COMMIT;
