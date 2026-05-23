-- V11: Tenant scoping. Pass K of the Spine multi-agent system.
--
-- Adds a `tenant_id` column to every big table that ingests outbox data
-- so future deployments can partition rows by client/tenant. Defaults to
-- 'default' so existing rows and pre-K daemons (which do not emit the
-- field) keep working unchanged.
--
-- Backward compat:
--   * Column is NOT NULL with a default, so pre-K outbox lines (no
--     tenant_id in JSON) ingest fine — Postgres fills the default.
--   * Watcher emits `tenant_id` when SPINE_TENANT is exported; otherwise
--     omits the column, leaving it at the default.
--   * The watcher retries inserts without the column on UndefinedColumn
--     so pre-V11 databases keep ingesting.

ALTER TABLE team ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE worker ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE assignment ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE cost_row ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE event ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE engagement ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE spine_instance ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE artifact ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE engagement_message ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default';

CREATE INDEX IF NOT EXISTS idx_team_tenant ON team (tenant_id);
CREATE INDEX IF NOT EXISTS idx_worker_tenant ON worker (tenant_id);
CREATE INDEX IF NOT EXISTS idx_cost_row_tenant ON cost_row (tenant_id);
CREATE INDEX IF NOT EXISTS idx_event_tenant ON event (tenant_id, ts);
CREATE INDEX IF NOT EXISTS idx_engagement_tenant ON engagement (
    tenant_id, status
);

-- v_tenants: per-tenant fleet snapshot. Distinct counts of teams /
-- workers / engagements rolled up by tenant_id so the dashboard can
-- render a tenant filter chip + a KPI card. UNION ALL pads the source
-- columns with NULLs so each subquery contributes exactly one column.
CREATE OR REPLACE VIEW v_tenants AS
SELECT
    tenant_id,
    COUNT(DISTINCT team_id) AS teams,
    COUNT(DISTINCT worker_id) AS workers,
    COUNT(DISTINCT engagement_id) AS engagements
FROM (
    SELECT
        tenant_id,
        team_id,
        NULL::UUID AS worker_id,
        NULL::UUID AS engagement_id
    FROM team
    UNION ALL
    SELECT
        tenant_id,
        NULL::UUID,
        worker_id,
        NULL::UUID
    FROM worker
    UNION ALL
    SELECT
        tenant_id,
        NULL::UUID,
        NULL::UUID,
        engagement_id
    FROM engagement
) AS u
GROUP BY tenant_id;
