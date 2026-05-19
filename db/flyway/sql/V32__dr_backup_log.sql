-- V32: DR backup + restore + heartbeat — Design Decisions #31, #32.
-- Backup runs + RTO-validated restore tests + cross-hub liveness heartbeats.

CREATE SCHEMA IF NOT EXISTS spine_dr;

COMMENT ON SCHEMA spine_dr IS
'Disaster recovery: backup runs, restore tests (RTO validation), cross-hub heartbeats.';

-- ─────────────────────────────────────────────────────────────────────
-- ENUMs
-- ─────────────────────────────────────────────────────────────────────

DO $$ BEGIN
    CREATE TYPE spine_dr.run_type AS ENUM ('continuous','snapshot');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE spine_dr.run_status AS ENUM ('in_progress','completed','failed','partial');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

COMMENT ON TYPE spine_dr.run_type IS 'Backup strategy: continuous (WAL streaming) | snapshot (point-in-time).';
COMMENT ON TYPE spine_dr.run_status IS 'Backup run lifecycle.';

-- ─────────────────────────────────────────────────────────────────────
-- backup_run — one row per backup execution
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_dr.backup_run (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_type spine_dr.run_type NOT NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    size_bytes bigint CHECK (size_bytes IS NULL OR size_bytes >= 0),
    target_storage text NOT NULL,
    encryption_kms_key_ref text,
    status spine_dr.run_status NOT NULL DEFAULT 'in_progress',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz,
    CONSTRAINT chk_backup_run_completed CHECK (
        (status = 'in_progress' AND completed_at IS NULL)
        OR (status <> 'in_progress')
    )
);

COMMENT ON TABLE spine_dr.backup_run IS 'Backup executions. encryption_kms_key_ref should always be set in production.';
COMMENT ON COLUMN spine_dr.backup_run.run_type IS 'continuous (WAL/CDC) | snapshot (point-in-time).';
COMMENT ON COLUMN spine_dr.backup_run.started_at IS 'Backup process start.';
COMMENT ON COLUMN spine_dr.backup_run.completed_at IS 'Backup process finish; NULL while in_progress.';
COMMENT ON COLUMN spine_dr.backup_run.size_bytes IS 'Total bytes written to target_storage.';
COMMENT ON COLUMN spine_dr.backup_run.target_storage IS 'Storage URI (s3://... / gs://... / azure://...).';
COMMENT ON COLUMN spine_dr.backup_run.encryption_kms_key_ref IS 'KMS key reference used to encrypt the backup.';
COMMENT ON COLUMN spine_dr.backup_run.status IS 'in_progress | completed | failed | partial.';

CREATE TRIGGER trg_backup_run_touch BEFORE UPDATE ON spine_dr.backup_run
FOR EACH ROW EXECUTE FUNCTION public._touch_updated_at();

CREATE INDEX idx_backup_run_run_type ON spine_dr.backup_run (run_type);
CREATE INDEX idx_backup_run_status ON spine_dr.backup_run (status);
CREATE INDEX idx_backup_run_started_at ON spine_dr.backup_run (started_at DESC);
CREATE INDEX idx_backup_run_completed_at ON spine_dr.backup_run (completed_at DESC);

-- ─────────────────────────────────────────────────────────────────────
-- restore_test — periodic restore-to-throwaway-environment validation
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_dr.restore_test (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    backup_run_id uuid NOT NULL,
    tested_at timestamptz NOT NULL DEFAULT now(),
    tested_in_env text NOT NULL,
    restore_succeeded boolean NOT NULL,
    rto_seconds integer CHECK (rto_seconds IS NULL OR rto_seconds >= 0),
    anomalies_jsonb jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz,
    CONSTRAINT fk_restore_test_backup FOREIGN KEY (backup_run_id) REFERENCES spine_dr.backup_run (id) ON DELETE RESTRICT
);

COMMENT ON TABLE spine_dr.restore_test IS 'Restore rehearsal results. rto_seconds provides measured RTO data.';
COMMENT ON COLUMN spine_dr.restore_test.backup_run_id IS 'Backup run restored during this test.';
COMMENT ON COLUMN spine_dr.restore_test.tested_at IS 'Test execution timestamp.';
COMMENT ON COLUMN spine_dr.restore_test.tested_in_env IS 'Test environment (staging | dr-sandbox | qa).';
COMMENT ON COLUMN spine_dr.restore_test.restore_succeeded IS 'Whether restore completed without data loss.';
COMMENT ON COLUMN spine_dr.restore_test.rto_seconds IS 'Measured Recovery Time Objective in seconds.';
COMMENT ON COLUMN spine_dr.restore_test.anomalies_jsonb IS 'Detected anomalies / data integrity issues.';

CREATE TRIGGER trg_restore_test_touch BEFORE UPDATE ON spine_dr.restore_test
FOR EACH ROW EXECUTE FUNCTION public._touch_updated_at();

CREATE INDEX idx_restore_test_backup_run_id ON spine_dr.restore_test (backup_run_id);
CREATE INDEX idx_restore_test_tested_at ON spine_dr.restore_test (tested_at DESC);
CREATE INDEX idx_restore_test_restore_succeeded ON spine_dr.restore_test (restore_succeeded);
CREATE INDEX idx_restore_test_tested_in_env ON spine_dr.restore_test (tested_in_env);

-- ─────────────────────────────────────────────────────────────────────
-- heartbeat — cross-hub liveness monitoring
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_dr.heartbeat (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_hub_id uuid NOT NULL,
    target_hub_id uuid NOT NULL,
    last_heartbeat timestamptz NOT NULL DEFAULT now(),
    status text NOT NULL DEFAULT 'healthy' CHECK (status IN ('healthy', 'degraded', 'unreachable', 'unknown')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz,
    CONSTRAINT uq_heartbeat UNIQUE (source_hub_id, target_hub_id)
);

COMMENT ON TABLE spine_dr.heartbeat IS 'Cross-hub liveness heartbeat for DR readiness monitoring. FKs to spine_federation.hub deferred to Wave 1.';
COMMENT ON COLUMN spine_dr.heartbeat.source_hub_id IS 'Primary hub emitting heartbeat; spine_federation.hub(hub_id).';
COMMENT ON COLUMN spine_dr.heartbeat.target_hub_id IS 'DR/standby hub receiving heartbeat.';
COMMENT ON COLUMN spine_dr.heartbeat.last_heartbeat IS 'Most recent successful heartbeat received.';
COMMENT ON COLUMN spine_dr.heartbeat.status IS 'healthy | degraded | unreachable | unknown.';

CREATE TRIGGER trg_heartbeat_touch BEFORE UPDATE ON spine_dr.heartbeat
FOR EACH ROW EXECUTE FUNCTION public._touch_updated_at();

CREATE INDEX idx_heartbeat_source_hub_id ON spine_dr.heartbeat (source_hub_id);
CREATE INDEX idx_heartbeat_target_hub_id ON spine_dr.heartbeat (target_hub_id);
CREATE INDEX idx_heartbeat_status ON spine_dr.heartbeat (status);
CREATE INDEX idx_heartbeat_last_heartbeat ON spine_dr.heartbeat (last_heartbeat DESC);
