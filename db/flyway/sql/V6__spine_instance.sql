-- V6: Spine instance registry — track every `team.sh up` invocation across
-- every host that points at this Postgres. Pass H (Spine Hub).
--
-- The schema is "remote hub ready": today Postgres runs locally and only
-- one host writes to it, but the same table works unchanged when the
-- DATABASE_URL is repointed at a shared server with N developer laptops
-- emitting heartbeats. Each row is one logical instance ("group"), not one
-- daemon process. The daemon-side SPINE_INSTANCE_ID is per-process; this
-- table's primary key is SPINE_GROUP_ID, a UUID minted by team.sh up that
-- every spawned daemon inherits.
--
-- Lifetime:
--   * `team.sh up`       -> emits InstanceStarted   -> row UPSERTed, status='alive'
--   * heartbeat.sh tick  -> emits InstanceHeartbeat -> last_seen_at bumped
--   * `team.sh down`     -> emits InstanceStopped   -> stopped_at + status='stopped'
--   * heartbeat silent   -> v_active_instances rolls effective_status to 'stale' / 'lost'
--
-- The 'lost' / 'stale' rollover is computed by the view rather than written
-- by anyone — that way the calculation is always live, and removing a
-- laptop from the wifi doesn't require any background process to "expire"
-- the row.

CREATE TYPE instance_status AS ENUM ('starting', 'alive', 'stopped', 'lost');

CREATE TABLE spine_instance (
    -- SPINE_GROUP_ID (one per `team.sh up`)
    instance_id text PRIMARY KEY,
    host_id text NOT NULL,
    os_user text,                                -- $USER on the host
    project_path text,                                -- absolute repo path
    project_slug text,                                -- basename of repo
    -- git rev-parse HEAD at startup
    version_sha text,
    -- first 12 chars of version_sha
    version_short text,
    -- semver from CHANGELOG.md if available
    spine_version text,
    started_at timestamptz NOT NULL DEFAULT now(),
    stopped_at timestamptz,
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    status instance_status NOT NULL DEFAULT 'starting',
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX idx_spine_instance_host ON spine_instance (host_id);
CREATE INDEX idx_spine_instance_alive ON spine_instance (status, last_seen_at)
WHERE status IN ('starting', 'alive');

-- v_active_instances: read-side projection used by the dashboard's Fleet
-- section. Computes "effective_status" from last_seen_at on every read so
-- nothing has to expire rows in the background:
--   * stopped              -> stopped         (terminal, set by InstanceStopped)
--   * last_seen > 180s ago -> lost
--   * last_seen 60..180s   -> stale
--   * otherwise            -> alive
CREATE OR REPLACE VIEW v_active_instances AS
SELECT
    instance_id,
    host_id,
    os_user,
    project_slug,
    project_path,
    version_short,
    spine_version,
    started_at,
    last_seen_at,
    extract(EPOCH FROM (now() - last_seen_at))::int AS seconds_since_seen,
    CASE
        WHEN status = 'stopped' THEN 'stopped'
        WHEN extract(EPOCH FROM (now() - last_seen_at)) > 180 THEN 'lost'
        WHEN extract(EPOCH FROM (now() - last_seen_at)) > 60 THEN 'stale'
        ELSE 'alive'
    END AS effective_status,
    metadata_json
FROM spine_instance;
