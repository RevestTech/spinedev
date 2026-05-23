-- V4: Read-side views — what the user-facing reporting layer queries.
--
-- These views are the payoff of Passes A-D: now that the daemon writes
-- cost_row + event into Postgres, the operator can ask interesting
-- questions without remembering joins. Each view here is shaped around
-- one such question.
--
-- CREATE OR REPLACE keeps them upgrade-friendly: a future versioned
-- migration can supersede any of these definitions in place.

-- v_cost_by_role_day: per-role daily rollups of invocations, wall time, tokens, and USD.
CREATE OR REPLACE VIEW v_cost_by_role_day AS
SELECT
    date_trunc('day', cr.ts)::date AS day,
    w.role_id AS role_id,
    count(*)::bigint AS invocations,
    sum(cr.wall_s)::numeric AS wall_s_total,
    sum(cr.tokens_in)::bigint AS tokens_in_total,
    sum(cr.tokens_out)::bigint AS tokens_out_total,
    sum(cr.cost_usd)::numeric AS cost_usd_total
FROM cost_row AS cr
JOIN assignment AS a ON a.assignment_id = cr.assignment_id
JOIN worker AS w ON w.worker_id = a.worker_id
JOIN role AS r ON r.role_id = w.role_id
GROUP BY date_trunc('day', cr.ts)::date, w.role_id;

-- v_cost_by_model: per-model totals plus the model table's own per-1k pricing for sanity-checking actuals.
CREATE OR REPLACE VIEW v_cost_by_model AS
SELECT
    m.model_id AS model_id,
    m.provider_id AS provider_id,
    m.name AS model_name,
    count(*)::bigint AS invocations,
    coalesce(sum(cr.tokens_in), 0)::bigint AS tokens_in_total,
    coalesce(sum(cr.tokens_out), 0)::bigint AS tokens_out_total,
    coalesce(sum(cr.cost_usd), 0)::numeric AS cost_usd_total,
    m.cost_in_usd_per_1k_tokens::numeric AS cost_usd_per_1k_in_avg,
    m.cost_out_usd_per_1k_tokens::numeric AS cost_usd_per_1k_out_avg
FROM cost_row AS cr
JOIN model AS m ON m.model_id = cr.model_id
JOIN provider AS p ON p.provider_id = m.provider_id
GROUP BY
    m.model_id,
    m.provider_id,
    m.name,
    m.cost_in_usd_per_1k_tokens,
    m.cost_out_usd_per_1k_tokens;

-- v_active_workers: workers not yet archived, with lifetime cost/invocation totals and the most recent cost row.
CREATE OR REPLACE VIEW v_active_workers AS
SELECT
    w.worker_id AS worker_id,
    w.team_id AS team_id,
    t.name AS team_name,
    w.role_id AS role_id,
    w.handle AS handle,
    w.host_id AS host_id,
    w.instance_id AS instance_id,
    w.status AS status,
    w.created_at AS created_at,
    cs.last_cost_ts AS last_cost_ts,
    coalesce(cs.lifetime_cost_usd, 0)::numeric AS lifetime_cost_usd,
    coalesce(cs.lifetime_invocations, 0)::bigint AS lifetime_invocations
FROM worker AS w
JOIN team AS t ON t.team_id = w.team_id
LEFT JOIN (
    SELECT
        a.worker_id AS worker_id,
        max(cr.ts) AS last_cost_ts,
        sum(cr.cost_usd)::numeric AS lifetime_cost_usd,
        count(*)::bigint AS lifetime_invocations
    FROM cost_row AS cr
    JOIN assignment AS a ON a.assignment_id = cr.assignment_id
    GROUP BY a.worker_id
) AS cs ON cs.worker_id = w.worker_id
WHERE w.archived_at IS NULL;

-- v_recent_events: last 200 lifecycle events with team/role/worker handles flattened for quick scanning.
CREATE OR REPLACE VIEW v_recent_events AS
SELECT
    e.event_id AS event_id,
    e.ts AS ts,
    e.type AS type,
    t.name AS team_name,
    w.role_id AS role_id,
    w.handle AS handle,
    w.host_id AS host_id,
    w.instance_id AS instance_id,
    e.payload_json AS payload_json
FROM (
    SELECT *
    FROM event
    ORDER BY ts DESC
    LIMIT 200
) AS e
LEFT JOIN worker AS w ON w.worker_id = e.worker_id
LEFT JOIN team AS t ON t.team_id = coalesce(e.team_id, w.team_id)
LEFT JOIN role AS r ON r.role_id = w.role_id;

-- v_cost_by_outcome: invocations grouped by rc-derived outcome (completed/failed/unknown); for finer-grained reap classification (timeout/stall/killed) see event type='Reaped'.
CREATE OR REPLACE VIEW v_cost_by_outcome AS
SELECT
    CASE
        WHEN cr.rc IS NULL THEN 'unknown'
        WHEN cr.rc = 0 THEN 'completed'
        ELSE 'failed'
    END AS outcome,
    count(*)::bigint AS invocations,
    sum(cr.wall_s)::numeric AS wall_s_total,
    sum(cr.cost_usd)::numeric AS cost_usd_total
FROM cost_row AS cr
GROUP BY 1;
