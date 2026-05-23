-- V8: Engagement artifacts + clarification messages. Pass I-2 of the
-- Spine multi-agent system.
--
-- Pass I-1 introduced the engagement row + the EngagementCreated path
-- (intake only). Pass I-2 adds:
--   * Additional URI columns to point at the artifacts each role
--     produces during hardening / planning (REQ.md, open-questions doc,
--     planner working notes, architect ADRs). The Pass-I-1 columns
--     (requirements_uri, plan_uri) remain authoritative for their
--     respective artifacts.
--   * An engagement_message child table that captures the question /
--     answer / comment thread between product, planner, architect and
--     the human across an engagement's lifetime.
--   * v_engagement_detail: the read-side projection used by the
--     dashboard's per-engagement page. Adds message_count so the
--     index table can render an "open questions" badge without an
--     extra round-trip.

ALTER TABLE engagement
ADD COLUMN req_uri TEXT,
ADD COLUMN open_questions_uri TEXT,
ADD COLUMN planner_report_uri TEXT,
ADD COLUMN architect_adr_uris JSONB NOT NULL DEFAULT '[]'::JSONB;

CREATE TABLE engagement_message (
    message_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id UUID NOT NULL REFERENCES engagement (
        engagement_id
    ) ON DELETE CASCADE,
    role TEXT NOT NULL,
    kind TEXT NOT NULL,
    body_md TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata_json JSONB NOT NULL DEFAULT '{}'::JSONB
);

CREATE INDEX idx_engagement_message_eng ON engagement_message (
    engagement_id, created_at
);

-- v_engagement_detail: per-engagement projection for the dashboard's
-- detail page. Adds message_count as a correlated subquery; the table
-- view (v_engagements_overview from V7) stays untouched so existing
-- callers keep working.
CREATE OR REPLACE VIEW v_engagement_detail AS
SELECT
    e.engagement_id,
    e.slug,
    e.title,
    e.client,
    e.status,
    e.requirements_uri,
    e.req_uri,
    e.open_questions_uri,
    e.planner_report_uri,
    e.plan_uri,
    e.architect_adr_uris,
    e.created_at,
    e.updated_at,
    e.approved_at,
    e.delivered_at,
    (
        SELECT count(*) FROM engagement_message AS m
        WHERE m.engagement_id = e.engagement_id
    ) AS message_count
FROM engagement AS e;
