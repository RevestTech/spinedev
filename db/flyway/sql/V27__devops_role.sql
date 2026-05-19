-- V27: DevOps / Operate subsystem — Design Decision #11.
-- 8 control planes + action audit log + versioned runbooks.

CREATE SCHEMA IF NOT EXISTS spine_devops;

COMMENT ON SCHEMA spine_devops IS
'Operate subsystem (6th corner): control planes, action audit log, versioned runbooks.';

-- ─────────────────────────────────────────────────────────────────────
-- ENUM: control_plane_name — exactly 8 per W2 reframe
-- ─────────────────────────────────────────────────────────────────────

DO $$ BEGIN
    CREATE TYPE spine_devops.control_plane_name AS ENUM (
        'ci_cd',
        'infrastructure',
        'secrets',
        'monitoring',
        'alerting',
        'deployment',
        'database',
        'networking'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

COMMENT ON TYPE spine_devops.control_plane_name IS '8 canonical Operate control planes per W2 reframe.';

-- ─────────────────────────────────────────────────────────────────────
-- control_plane — logical plane instance per project
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_devops.control_plane (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plane_name spine_devops.control_plane_name NOT NULL,
    project_id uuid,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'disabled', 'error')),
    last_invoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz,
    CONSTRAINT fk_control_plane_project FOREIGN KEY (project_id) REFERENCES spine_hub.project (id) ON DELETE SET NULL
);

COMMENT ON TABLE spine_devops.control_plane IS 'Operate control plane instances; one row per (plane_name, project_id).';
COMMENT ON COLUMN spine_devops.control_plane.plane_name IS 'One of the 8 canonical control planes.';
COMMENT ON COLUMN spine_devops.control_plane.project_id IS 'Project; NULL = hub-global plane.';
COMMENT ON COLUMN spine_devops.control_plane.status IS 'active | paused | disabled | error.';
COMMENT ON COLUMN spine_devops.control_plane.last_invoked_at IS 'Most recent action dispatch timestamp.';

CREATE TRIGGER trg_control_plane_touch BEFORE UPDATE ON spine_devops.control_plane
FOR EACH ROW EXECUTE FUNCTION public._touch_updated_at();

CREATE INDEX idx_control_plane_plane_name ON spine_devops.control_plane (plane_name);
CREATE INDEX idx_control_plane_project_id ON spine_devops.control_plane (project_id);
CREATE INDEX idx_control_plane_status ON spine_devops.control_plane (status);

-- ─────────────────────────────────────────────────────────────────────
-- action_log — append-only action audit per plane
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_devops.action_log (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plane_id uuid NOT NULL,
    action text NOT NULL,
    payload_jsonb jsonb NOT NULL DEFAULT '{}',
    actor_user_id uuid,
    ts timestamptz NOT NULL DEFAULT now(),
    audit_chain_anchor bytea,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_action_log_plane FOREIGN KEY (plane_id) REFERENCES spine_devops.control_plane (id) ON DELETE RESTRICT
);

COMMENT ON TABLE spine_devops.action_log IS 'Append-only DevOps action log per control plane.';
COMMENT ON COLUMN spine_devops.action_log.plane_id IS 'Control plane that received the action.';
COMMENT ON COLUMN spine_devops.action_log.action IS 'deploy | rollback | rotate_secret | scale_up | restart | drain | etc.';
COMMENT ON COLUMN spine_devops.action_log.payload_jsonb IS 'Action-specific parameters (image tag, env, replica count).';
COMMENT ON COLUMN spine_devops.action_log.actor_user_id IS 'Triggering user; NULL for automated pipelines. FK to spine_identity.user_link in Wave 1.';
COMMENT ON COLUMN spine_devops.action_log.ts IS 'Authoritative event timestamp.';
COMMENT ON COLUMN spine_devops.action_log.audit_chain_anchor IS 'SHA-256 of spine_audit.audit_record row; FK enforced in Wave 1.';

CREATE INDEX idx_action_log_plane_id ON spine_devops.action_log (plane_id);
CREATE INDEX idx_action_log_action ON spine_devops.action_log (action);
CREATE INDEX idx_action_log_actor_user_id ON spine_devops.action_log (actor_user_id);
CREATE INDEX idx_action_log_ts ON spine_devops.action_log (ts DESC);

-- ─────────────────────────────────────────────────────────────────────
-- runbook — versioned runbook definitions per plane
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_devops.runbook (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plane_id uuid NOT NULL,
    name text NOT NULL,
    version text NOT NULL,
    content_hash bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_runbook_plane FOREIGN KEY (plane_id) REFERENCES spine_devops.control_plane (id) ON DELETE CASCADE,
    CONSTRAINT uq_runbook_plane_name_version UNIQUE (plane_id, name, version)
);

COMMENT ON TABLE spine_devops.runbook IS 'Versioned runbook definitions; content_hash enables integrity verification.';
COMMENT ON COLUMN spine_devops.runbook.plane_id IS 'Owning control plane.';
COMMENT ON COLUMN spine_devops.runbook.name IS 'Runbook name (e.g. blue-green-deploy, db-failover).';
COMMENT ON COLUMN spine_devops.runbook.version IS 'Semver string.';
COMMENT ON COLUMN spine_devops.runbook.content_hash IS 'SHA-256 of canonical runbook content at this version.';

CREATE INDEX idx_runbook_plane_id ON spine_devops.runbook (plane_id);
CREATE INDEX idx_runbook_name ON spine_devops.runbook (name);
