-- V13: Machine vitals — Pass M.
--
-- Every InstanceHeartbeat now carries a small "vitals" snapshot of the host:
-- total CPU%, memory used/total, disk used/total, load averages, and the
-- Spine-attributed totals (CPU% and RSS summed across all spine_* daemons,
-- plus the count of those processes). We materialize the LATEST snapshot
-- on the spine_instance row for fast dashboard reads, and we append every
-- snapshot into instance_vitals so admins can see how Spine is impacting
-- the host over time.
--
-- Backward compat:
--   * All new columns are nullable / have NULL semantics; pre-M daemons
--     that don't emit vitals still ingest cleanly (the watcher just skips
--     the UPDATE for those rows).
--   * The watcher probes for column presence (mirror of the V11 tenant_id
--     pattern) so a pre-V13 database keeps ingesting if the migration
--     hasn't been applied.

-- Latest vitals materialized on the instance row for fast dashboard reads.
ALTER TABLE spine_instance
ADD COLUMN cpu_pct REAL,          -- 0..100 total host CPU
ADD COLUMN mem_used_mb BIGINT,
ADD COLUMN mem_total_mb BIGINT,
ADD COLUMN disk_used_gb REAL,
ADD COLUMN disk_total_gb REAL,
ADD COLUMN load_avg_1m REAL,
ADD COLUMN load_avg_5m REAL,
ADD COLUMN load_avg_15m REAL,
ADD COLUMN spine_cpu_pct REAL,          -- summed across spine_* processes
ADD COLUMN spine_mem_mb BIGINT,
ADD COLUMN spine_proc_count INT,           -- # of spine_* processes seen
ADD COLUMN vitals_at TIMESTAMPTZ;

-- Time-series of every heartbeat's vitals. The instance_vitals table is
-- append-only; downsampling/retention is operator's choice (e.g., a cron
-- job that deletes rows older than 30 days).
CREATE TABLE instance_vitals (
    instance_id TEXT NOT NULL REFERENCES spine_instance (
        instance_id
    ) ON DELETE CASCADE,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    cpu_pct REAL,
    mem_used_mb BIGINT,
    mem_total_mb BIGINT,
    disk_used_gb REAL,
    disk_total_gb REAL,
    load_avg_1m REAL,
    load_avg_5m REAL,
    load_avg_15m REAL,
    spine_cpu_pct REAL,
    spine_mem_mb BIGINT,
    spine_proc_count INT,
    PRIMARY KEY (instance_id, ts)
);

CREATE INDEX idx_instance_vitals_ts ON instance_vitals (ts);

CREATE OR REPLACE VIEW v_instance_vitals_latest AS
SELECT
    i.instance_id,
    i.host_id,
    i.project_slug,
    i.os_user,
    i.cpu_pct,
    i.mem_used_mb,
    i.mem_total_mb,
    i.disk_used_gb,
    i.disk_total_gb,
    i.load_avg_1m,
    i.load_avg_5m,
    i.load_avg_15m,
    i.spine_cpu_pct,
    i.spine_mem_mb,
    i.spine_proc_count,
    i.vitals_at,
    CASE
        WHEN
            i.mem_total_mb > 0
            THEN (i.mem_used_mb::FLOAT / i.mem_total_mb * 100)
    END AS mem_used_pct,
    CASE
        WHEN i.disk_total_gb > 0 THEN (i.disk_used_gb / i.disk_total_gb * 100)
    END AS disk_used_pct,
    CASE
        WHEN
            i.spine_cpu_pct IS NULL OR i.cpu_pct IS NULL OR i.cpu_pct = 0
            THEN NULL
        ELSE (i.spine_cpu_pct / i.cpu_pct * 100)
    END AS spine_share_pct
FROM spine_instance AS i
WHERE i.status != 'stopped';
