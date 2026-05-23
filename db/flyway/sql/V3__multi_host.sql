-- V3: Multi-host support — add host_id and instance_id to worker/assignment.
--
-- Why: in central-server mode, multiple machines may each run a daemon for
-- the same logical worker handle (e.g., "engineer-alpha" exists in team
-- "atlas", and laptops X and Y both have a process claiming that handle).
-- Without a host/instance discriminator, the partial unique index from V1
-- (assignment_one_active_per_worker) would FK-collide the moment a second
-- host writes.
--
-- This migration:
--   1. Adds `host_id` (logical machine name) and `instance_id` (pid+boot
--      tag, unique per daemon process) to both `worker` and `assignment`.
--   2. Replaces the partial unique index with one keyed on
--      (worker_id, instance_id) so each daemon process can hold at most
--      one active assignment but two daemons can coexist.
--   3. Defaults existing rows to host_id='local', instance_id='legacy' so
--      pre-migration data continues to satisfy NOT NULL.
--
-- Forward compatibility: A16 (Session/Run as a first-class entity) in
-- V2_BACKLOG.md is the eventual home for this data. When that table lands,
-- these columns can be lifted into FKs onto `session`.

-- ─────────────────────────────────────────────────────────────────────
-- Columns
-- ─────────────────────────────────────────────────────────────────────

ALTER TABLE worker
ADD COLUMN host_id TEXT NOT NULL DEFAULT 'local',
ADD COLUMN instance_id TEXT NOT NULL DEFAULT 'legacy';

ALTER TABLE assignment
ADD COLUMN host_id TEXT NOT NULL DEFAULT 'local',
ADD COLUMN instance_id TEXT NOT NULL DEFAULT 'legacy';

-- Drop the defaults — new rows must specify host/instance explicitly so we
-- don't silently mask "forgot to populate it" bugs from a watcher.
ALTER TABLE worker ALTER COLUMN host_id DROP DEFAULT;
ALTER TABLE worker ALTER COLUMN instance_id DROP DEFAULT;
ALTER TABLE assignment ALTER COLUMN host_id DROP DEFAULT;
ALTER TABLE assignment ALTER COLUMN instance_id DROP DEFAULT;

-- ─────────────────────────────────────────────────────────────────────
-- Indexes
-- ─────────────────────────────────────────────────────────────────────

-- Replace the V1 single-active-per-worker constraint with one that lets
-- two daemons (different instance_id) each hold an active assignment for
-- the same logical worker handle.
DROP INDEX IF EXISTS assignment_one_active_per_worker;

CREATE UNIQUE INDEX assignment_one_active_per_instance
ON assignment (worker_id, instance_id)
WHERE status = 'active';

-- Lookup index for "which workers are running on host X right now".
CREATE INDEX idx_worker_host_instance
ON worker (host_id, instance_id)
WHERE archived_at IS NULL;

CREATE INDEX idx_assignment_host_instance
ON assignment (host_id, instance_id);
