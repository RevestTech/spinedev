-- V5: Invocation duration analytics — pair InvocationStarted events with
-- their EARLIEST subsequent terminal event on the same assignment so we
-- can compute real wall-clock duration per invocation.
--
-- Pass E. The daemon emits one InvocationStarted event right before the
-- agent process is spawned and one terminal event (Reaped, ReportWritten,
-- PlanWritten, AggregateCompleted, WorkerCompleted) after it returns.
-- This view answers the operator question "how long did each invocation
-- actually take, and which terminal class did it land in?" without
-- requiring callers to remember the join.
--
-- Implementation notes:
--   * The payload_json column stores the FULL outer outbox envelope, so
--     the inner payload values live one level deeper (->'payload'->>'k').
--   * We use LEFT JOIN LATERAL so in-flight invocations (no terminal
--     event yet) still show up — ended_at and duration_s are NULL.
--   * No ORDER BY in the view definition; callers should ORDER BY
--     started_at DESC at the call site to keep the planner free to use
--     event indexes on type/assignment_id.

CREATE OR REPLACE VIEW v_invocation_durations AS
SELECT
    s.event_id AS event_id,
    s.ts AS started_at,
    t.ts AS ended_at,
    CASE
        WHEN t.ts IS NULL THEN NULL
        ELSE EXTRACT(EPOCH FROM (t.ts - s.ts))::numeric
    END AS duration_s,
    w.role_id AS role_id,
    w.handle AS handle,
    w.host_id AS host_id,
    w.instance_id AS instance_id,
    (s.payload_json -> 'payload' ->> 'tier') AS tier,
    (s.payload_json -> 'payload' ->> 'classification') AS classification,
    t.type AS terminal_type,
    (t.payload_json -> 'payload' ->> 'outcome') AS outcome,
    s.assignment_id AS assignment_id
FROM event AS s
LEFT JOIN worker AS w ON w.worker_id = s.worker_id
LEFT JOIN LATERAL (
    SELECT
        e2.ts,
        e2.type,
        e2.payload_json
    FROM event AS e2
    WHERE
        e2.assignment_id = s.assignment_id
        AND e2.ts >= s.ts
        AND e2.type IN (
            'Reaped', 'ReportWritten', 'PlanWritten',
            'AggregateCompleted', 'WorkerCompleted'
        )
    ORDER BY e2.ts ASC, e2.event_id ASC
    LIMIT 1
) AS t ON TRUE
WHERE s.type = 'InvocationStarted';
