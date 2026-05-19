-- V17: Portfolio management — queue table + cross-project rollup views.
--
-- Implements STORY-9.5.2 (per-project resource limits → queue) and
-- STORY-9.5.3 (cross-project rollups) from docs/BACKLOG.md EPIC-9.5; maps
-- to docs/PRD.md REQ-INIT-9 §9.5 FR-6. Consumed by
-- orchestrator/lib/portfolio.sh.
--
-- All views are read-only by design (no triggers, no rules). Single-writer
-- table is `spine_lifecycle.portfolio_queue`; portfolio.sh is the only
-- caller that INSERTs / UPDATEs it.

BEGIN;

-- portfolio_queue — overflow buffer for directives that exceeded a
-- project's max_parallel_directives at dispatch time (STORY-9.5.2).
CREATE TABLE IF NOT EXISTS spine_lifecycle.portfolio_queue (
    id BIGSERIAL PRIMARY KEY,
    project_id BIGINT NOT NULL REFERENCES spine_lifecycle.project (id) ON DELETE CASCADE,
    subsystem TEXT NOT NULL,
    role TEXT NOT NULL,
    directive_payload JSONB NOT NULL,
    queued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    dispatched_at TIMESTAMPTZ,
    priority INTEGER NOT NULL DEFAULT 100,
    CONSTRAINT portfolio_queue_subsystem_chk CHECK (subsystem IN ('plan', 'build', 'verify'))
);
COMMENT ON TABLE spine_lifecycle.portfolio_queue IS 'Overflow queue: directives rejected by portfolio_can_dispatch land here until capacity frees.';
COMMENT ON COLUMN spine_lifecycle.portfolio_queue.priority IS 'Lower integer = higher priority. Drain pulls ORDER BY priority ASC, queued_at ASC.';
COMMENT ON COLUMN spine_lifecycle.portfolio_queue.directive_payload IS 'JSON envelope (subsystem, role, directive_ref, ...) preserved verbatim for the eventual router.sh dispatch.';
COMMENT ON COLUMN spine_lifecycle.portfolio_queue.dispatched_at IS 'NULL = still queued; set by portfolio_drain_queue() when handed to router.sh.';

CREATE INDEX IF NOT EXISTS idx_portfolio_queue_open
ON spine_lifecycle.portfolio_queue (project_id, dispatched_at) WHERE dispatched_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_portfolio_queue_priority
ON spine_lifecycle.portfolio_queue (priority ASC, queued_at ASC) WHERE dispatched_at IS NULL;

-- v_projects_by_phase — count of active/paused projects per phase.
CREATE OR REPLACE VIEW spine_lifecycle.v_projects_by_phase AS
SELECT
    current_phase AS phase,
    COUNT(*)::BIGINT AS project_count,
    COUNT(*) FILTER (WHERE status = 'paused')::BIGINT AS paused_count,
    MIN(updated_at) AS oldest_in_phase,
    MAX(updated_at) AS newest_in_phase
FROM spine_lifecycle.project
WHERE status IN ('active', 'paused')
GROUP BY current_phase
ORDER BY current_phase;
COMMENT ON VIEW spine_lifecycle.v_projects_by_phase IS
'Count of active/paused projects per phase. Consumers: dashboard portfolio heatmap, `spine portfolio status`.';

-- v_blocked_projects — paused OR metadata.blocked=true, with reason.
CREATE OR REPLACE VIEW spine_lifecycle.v_blocked_projects AS
SELECT
    id AS project_id,
    project_uuid AS uuid,
    name,
    current_phase,
    status,
    COALESCE(
        metadata ->> 'block_reason',
        CASE
            WHEN status = 'paused' THEN 'project paused'
            ELSE 'metadata.blocked=true'
        END
    ) AS reason,
    updated_at
FROM spine_lifecycle.project
WHERE
    status = 'paused'
    OR COALESCE((metadata ->> 'blocked')::BOOL, FALSE)
ORDER BY updated_at DESC;
COMMENT ON VIEW spine_lifecycle.v_blocked_projects IS
'Projects requiring operator attention (paused or metadata.blocked). Consumers: dashboard "what is stuck" card, alerting.';

-- v_active_directives — every in-flight directive across every project.
CREATE OR REPLACE VIEW spine_lifecycle.v_active_directives AS
SELECT
    rh.project_id,
    p.name AS project_name,
    p.current_phase AS project_phase,
    rh.phase AS dispatched_phase,
    rh.subsystem,
    rh.role,
    rh.directive_ref,
    rh.dispatched_at,
    EXTRACT(EPOCH FROM (NOW() - rh.dispatched_at))::INT AS age_seconds,
    rh.metadata
FROM spine_lifecycle.route_history AS rh
JOIN spine_lifecycle.project AS p ON p.id = rh.project_id
WHERE rh.dispatched_at IS NOT NULL AND rh.completed_at IS NULL
ORDER BY rh.dispatched_at ASC;
COMMENT ON VIEW spine_lifecycle.v_active_directives IS
'Currently in-flight directives across the whole portfolio. Consumers: dispatch monitor, stuck-directive watchdog.';

-- v_portfolio_health — single-row fleet snapshot for the dashboard header.
CREATE OR REPLACE VIEW spine_lifecycle.v_portfolio_health AS
SELECT
    (
        SELECT COUNT(*) FROM spine_lifecycle.project
        WHERE status = 'active'
    )::BIGINT AS active_projects,
    (SELECT COUNT(*) FROM spine_lifecycle.v_blocked_projects)::BIGINT AS blocked_projects,
    (SELECT COUNT(*) FROM spine_lifecycle.v_active_directives)::BIGINT AS in_flight_directives,
    (
        SELECT COUNT(*) FROM spine_lifecycle.portfolio_queue
        WHERE dispatched_at IS NULL
    )::BIGINT AS queued_directives,
    COALESCE((
        SELECT SUM(cost_usd) FROM spine_recording.costs
        WHERE ts >= DATE_TRUNC('day', NOW())
    ), 0)::NUMERIC AS spend_today_usd,
    COALESCE((
        SELECT SUM(cost_usd) FROM spine_recording.costs
        WHERE ts >= DATE_TRUNC('month', NOW())
    ), 0)::NUMERIC AS spend_month_usd,
    NOW() AS computed_at;
COMMENT ON VIEW spine_lifecycle.v_portfolio_health IS
'One-row fleet snapshot: active/blocked projects, in-flight + queued directives, spend today/month. Consumers: dashboard header, /healthz.';

-- v_project_resource_usage — per-project drill-down companion.
CREATE OR REPLACE VIEW spine_lifecycle.v_project_resource_usage AS
SELECT
    p.id AS project_id,
    p.project_uuid AS uuid,
    p.name,
    p.current_phase,
    p.status,
    COALESCE((p.metadata ->> 'max_parallel_directives')::INT, 3) AS max_parallel_directives,
    COALESCE((p.metadata ->> 'max_workers')::INT, 2) AS max_workers,
    (
        SELECT COUNT(*) FROM spine_lifecycle.route_history AS rh
        WHERE rh.project_id = p.id AND rh.completed_at IS NULL
    )::BIGINT AS in_flight,
    (
        SELECT COUNT(*) FROM spine_lifecycle.portfolio_queue AS q
        WHERE q.project_id = p.id AND q.dispatched_at IS NULL
    )::BIGINT AS queue_depth,
    COALESCE((
        SELECT SUM(c.cost_usd) FROM spine_recording.costs AS c
        WHERE
            c.project_id = p.id
            AND c.ts >= DATE_TRUNC('day', NOW())
    ), 0)::NUMERIC AS cost_today_usd
FROM spine_lifecycle.project AS p
WHERE p.status IN ('active', 'paused')
ORDER BY p.id;
COMMENT ON VIEW spine_lifecycle.v_project_resource_usage IS
'Per-project resource snapshot: limit, in-flight, queue depth, cost today. Consumers: `spine portfolio status`, per-project dashboard tile.';

COMMIT;
