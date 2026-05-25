-- V37: Durable project role terminal log lines (Hub SPA pipeline terminal).
-- Replaces in-process ring buffer as the sole source of truth across restarts.
-- Append-only; no hash chain for v1.

BEGIN;

CREATE TABLE IF NOT EXISTS spine_hub.project_role_log (
    id BIGSERIAL PRIMARY KEY,
    project_uuid TEXT NOT NULL,
    role TEXT,
    message TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'info',
    formatted TEXT,
    ts TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE spine_hub.project_role_log IS
'Durable role activity lines for the embedded pipeline terminal UI.';
COMMENT ON COLUMN spine_hub.project_role_log.project_uuid IS
'External project UUID (spine_lifecycle.project.project_uuid::text).';
COMMENT ON COLUMN spine_hub.project_role_log.ts IS
'Event timestamp when the role emitted the line.';

CREATE INDEX IF NOT EXISTS idx_project_role_log_project_uuid_id
    ON spine_hub.project_role_log (project_uuid, id);

COMMIT;
