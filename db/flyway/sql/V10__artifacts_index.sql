-- V10: Artifact tracking for engagements. Pass J of the Spine multi-agent
-- system.
--
-- The V1 schema introduced an `artifact` table 1:1-linked to an assignment.
-- Pass J adds a nullable engagement_id FK so the watcher (Pass J) can attach
-- agent-produced artifacts (PR URLs, file outputs, deploy IDs, ...) directly
-- to their parent engagement, even when no assignment row exists.
--
-- Backward compat: the column is nullable and the index is partial so pre-J
-- ingest paths are unaffected. The watcher gracefully retries inserts
-- without the column when the migration hasn't applied yet.

ALTER TABLE artifact
ADD COLUMN IF NOT EXISTS engagement_id UUID REFERENCES engagement (
    engagement_id
);

-- Pass J: an artifact can now be attached to an engagement without an
-- assignment (e.g., a deploy URL discovered during dispatch, before any
-- single worker owns it). Drop the NOT NULL so the watcher can insert a
-- row carrying engagement_id alone.
ALTER TABLE artifact
ALTER COLUMN assignment_id DROP NOT NULL;

CREATE INDEX IF NOT EXISTS idx_artifact_engagement ON artifact (engagement_id)
WHERE engagement_id IS NOT NULL;

-- v_engagement_artifacts: per-engagement read-side projection used by the
-- dashboard's per-engagement detail page. The LEFT JOINs let artifacts that
-- aren't backed by an assignment row (assignment_id is NULL) still surface
-- with role_id / handle as NULL.
CREATE OR REPLACE VIEW v_engagement_artifacts AS
SELECT
    e.engagement_id,
    e.slug,
    a.artifact_id,
    a.kind,
    a.uri,
    a.title,
    a.metadata_json,
    a.created_at,
    ass.worker_id,
    w.role_id,
    w.handle
FROM engagement AS e
JOIN artifact AS a ON a.engagement_id = e.engagement_id
LEFT JOIN assignment AS ass ON ass.assignment_id = a.assignment_id
LEFT JOIN worker AS w ON w.worker_id = ass.worker_id;
