-- V9: Engagement linkage on hot tables. Pass I-3 of the Spine multi-agent
-- system.
--
-- Pass I-2 left cost_row and event with no way to attribute their entries
-- to a particular engagement. Pass I-3 adds a nullable engagement_id FK to
-- both tables so downstream sub-directives (written by the conductor / by
-- managers fanned-out from an approved plan) can carry the parent
-- engagement id down to every worker invocation. Cost roll-ups and the
-- per-engagement timeline view both pivot off this column.
--
-- Backward compat: the column is nullable. Pre-Pass-I-3 cost_row and event
-- rows have NULL engagement_id and are still valid; the daemon outbox and
-- the watcher both treat the engagement_id field as optional. The
-- partial indexes only cover non-NULL rows so general cost / event
-- workloads are not impacted.

ALTER TABLE cost_row
ADD COLUMN engagement_id UUID REFERENCES engagement (engagement_id);

ALTER TABLE event
ADD COLUMN engagement_id UUID REFERENCES engagement (engagement_id);

CREATE INDEX idx_cost_row_engagement ON cost_row (engagement_id)
WHERE engagement_id IS NOT NULL;
CREATE INDEX idx_event_engagement ON event (engagement_id, ts)
WHERE engagement_id IS NOT NULL;

-- v_engagement_timeline: a chronological projection of every event that
-- carries an engagement_id, joined to the worker/role that emitted it so
-- the dashboard's per-engagement timeline view can render role badges
-- without a second query. Latest first is the dashboard's preferred
-- order; we leave the ordering to the caller so the view stays composable.
CREATE OR REPLACE VIEW v_engagement_timeline AS
SELECT
    e.engagement_id,
    e.slug,
    ev.event_id,
    ev.ts,
    ev.type,
    w.role_id,
    w.handle,
    w.host_id,
    ev.payload_json
FROM event AS ev
JOIN engagement AS e ON e.engagement_id = ev.engagement_id
LEFT JOIN worker AS w ON w.worker_id = ev.worker_id;

-- v_engagement_costs: per-engagement aggregates of invocations, wall time,
-- tokens, USD spend, and the number of distinct roles/workers that
-- contributed. LEFT JOIN keeps engagements with zero cost rows in the
-- result set (with all counts/sums at 0) so the dashboard can render a
-- "no spend yet" panel uniformly.
CREATE OR REPLACE VIEW v_engagement_costs AS
SELECT
    e.engagement_id,
    e.slug,
    COUNT(cr.assignment_id) AS invocations,
    COALESCE(SUM(cr.wall_s), 0)::FLOAT AS wall_s,
    COALESCE(SUM(cr.tokens_in), 0)::INT AS tokens_in,
    COALESCE(SUM(cr.tokens_out), 0)::INT AS tokens_out,
    ROUND(COALESCE(SUM(cr.cost_usd), 0)::NUMERIC, 6)::FLOAT AS cost_usd,
    COUNT(DISTINCT w.role_id) AS roles_used,
    COUNT(DISTINCT a.worker_id) AS workers_used
FROM engagement AS e
LEFT JOIN cost_row AS cr ON cr.engagement_id = e.engagement_id
LEFT JOIN assignment AS a ON a.assignment_id = cr.assignment_id
LEFT JOIN worker AS w ON w.worker_id = a.worker_id
GROUP BY e.engagement_id, e.slug;
