-- V12: Spine release channels — Pass L (Spine Hub Pillar 2, code distribution).
--
-- The vision: SpineDevelopment is a *templating* project. Installations consume
-- it; the scripts/role-prompts/recipes they end up with come from this repo.
-- This migration adds the data model for an admin to promote a specific git
-- commit of the SpineDevelopment template to one of three release channels
-- (stable / beta / canary) and for fleet members to fast-forward to it via
-- the updater daemon (lib/updater.sh).
--
-- Read-side views:
--   v_release_heads     -- latest non-archived release per channel
--   v_instance_drift    -- per-instance drift status (current/drifted/...)
--
-- Pillar 1 of the Hub (telemetry / heartbeats / cost projection) is untouched;
-- the new tables ride alongside spine_instance + cost_row.

CREATE TYPE release_channel AS ENUM ('stable', 'beta', 'canary');

CREATE TABLE spine_release (
    release_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    channel release_channel NOT NULL,
    commit_sha text NOT NULL,
    short_sha text NOT NULL,
    ref text,                          -- branch/tag name from git
    notes_md text,                          -- optional release notes
    promoted_by text,                          -- human who marked it good
    promoted_at timestamptz NOT NULL DEFAULT now(),
    archived_at timestamptz,
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (channel, commit_sha)
);

CREATE INDEX idx_spine_release_channel ON spine_release (
    channel, promoted_at DESC
)
WHERE archived_at IS NULL;

-- Latest known-good per channel. The updater queries this view (when it has a
-- SPINE_DB_URL) to decide which commit to fast-forward to. Archived releases
-- are excluded so an admin can "roll back" the channel by archiving the bad
-- release; fleet members will pick the next-newest non-archived one on their
-- next tick.
CREATE OR REPLACE VIEW v_release_heads AS
SELECT DISTINCT ON (channel)
    channel::text AS channel,
    commit_sha,
    short_sha,
    ref,
    notes_md,
    promoted_by,
    promoted_at
FROM spine_release
WHERE archived_at IS NULL
ORDER BY channel, promoted_at DESC;

-- Per-instance version drift. Compares each running instance's
-- version_sha (captured at `team.sh up` time in spine_instance.version_sha)
-- against the head of its declared channel. Channel comes from
-- spine_instance.metadata_json->>'channel' which the watcher populates from
-- the InstanceStarted payload (SPINE_UPDATE_CHANNEL env var, default 'stable').
--
-- Status values:
--   current          version_sha matches the channel head
--   drifted          version_sha is set, doesn't match head, head exists
--   unversioned      version_sha is NULL or the sentinel 'unknown'
--   unknown_channel  no head exists for the instance's channel (no release
--                    has been promoted yet, or the channel label is bogus)
--
-- Excludes stopped instances so the dashboard doesn't show drift status for
-- machines that aren't running. Stale/lost rows are still included because a
-- laptop being offline is exactly when "is this version current?" matters.
CREATE OR REPLACE VIEW v_instance_drift AS
SELECT
    i.instance_id,
    i.host_id,
    i.os_user,
    i.project_slug,
    i.version_short AS instance_short,
    i.version_sha AS instance_sha,
    coalesce(i.metadata_json ->> 'channel', 'stable') AS channel,
    rh.short_sha AS head_short,
    rh.commit_sha AS head_sha,
    CASE
        WHEN rh.commit_sha IS NULL THEN 'unknown_channel'
        WHEN i.version_sha = rh.commit_sha THEN 'current'
        WHEN
            i.version_sha IS NULL OR i.version_sha = 'unknown'
            THEN 'unversioned'
        ELSE 'drifted'
    END AS drift_status,
    i.last_seen_at
FROM spine_instance AS i
LEFT JOIN v_release_heads AS rh
    ON rh.channel = coalesce(i.metadata_json ->> 'channel', 'stable')
WHERE i.status != 'stopped';
