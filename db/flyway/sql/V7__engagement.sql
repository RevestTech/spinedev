-- V7: Engagement entity — a first-class client engagement (piece of client
-- work) tracked end-to-end through requirements, hardening, planning,
-- approval, execution, and delivery. Pass I-1 of the Spine multi-agent
-- system. Pass I-1 only introduces the table, the status enum, an
-- overview view, and the EngagementCreated -> 'intake' path. Status
-- transitions beyond 'intake' are written by the watcher in later passes.
--
-- Engagement vs task
-- ------------------
-- The pre-existing `task` table (V1) is a low-level work item produced
-- inside an engagement during execution. An engagement is the parent
-- "consulting-firm project" envelope: one client brief in, many tasks
-- out. They are intentionally separate so engagement lifecycle (intake
-- to delivered) doesn't pollute task semantics, and so the dashboard's
-- new Engagements section can be added without touching anything that
-- references task.
--
-- Identity
-- --------
--   * engagement_id : UUID surrogate, server-side default gen_random_uuid()
--   * (team_id, slug) : human-readable unique key. The slug is built
--     from the title (lowercased, non-alnum collapsed to '-') with a
--     '-YYYY-MM-DD' suffix so two engagements with the same title
--     submitted on different days don't collide. Suffix-with-counter
--     fallback lives in the dashboard backend.

CREATE TYPE engagement_status AS ENUM (
    'intake',             -- requirements submitted, product not yet picked up
    'hardening',          -- product is asking clarifying questions
    'planning',           -- requirements finalized, planner/architect working
    'awaiting_approval',
    'executing',          -- conductor is dispatching to squads
    'delivered',
    'cancelled'
);

CREATE TABLE engagement (
    engagement_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id uuid NOT NULL REFERENCES team (team_id),
    title text NOT NULL,
    slug text NOT NULL,
    client text,
    status engagement_status NOT NULL DEFAULT 'intake',
    requirements_uri text,
    plan_uri text,
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    approved_at timestamptz,
    delivered_at timestamptz,
    closed_at timestamptz,
    UNIQUE (team_id, slug)
);

CREATE INDEX idx_engagement_status ON engagement (status);
CREATE INDEX idx_engagement_team ON engagement (team_id);

CREATE TRIGGER trg_engagement_updated_at
BEFORE UPDATE ON engagement
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

-- v_engagements_overview: read-side projection used by the dashboard's
-- Engagements section and the GET /api/engagements endpoint. Recomputes
-- age_seconds on every read so the row stays correct without a tick.
CREATE OR REPLACE VIEW v_engagements_overview AS
SELECT
    e.engagement_id,
    e.slug,
    e.title,
    e.client,
    e.status,
    e.requirements_uri,
    e.plan_uri,
    e.created_at,
    e.updated_at,
    e.approved_at,
    e.delivered_at,
    extract(EPOCH FROM (now() - e.created_at))::int AS age_seconds
FROM engagement AS e;
