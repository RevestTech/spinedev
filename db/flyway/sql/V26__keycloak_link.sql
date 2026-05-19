-- V26: Keycloak identity link — Design Decision #25.
-- Bridge Keycloak OIDC subjects to internal Spine users + group→role mapping + session audit.

CREATE SCHEMA IF NOT EXISTS spine_identity;

COMMENT ON SCHEMA spine_identity IS
'Keycloak OIDC identity bridge: user_link, group_role_mapping, session_audit.';

-- ─────────────────────────────────────────────────────────────────────
-- user_link — Keycloak sub ↔ internal Spine user UUID
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_identity.user_link (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    keycloak_sub uuid NOT NULL UNIQUE,
    internal_user_id uuid UNIQUE,
    email text NOT NULL,
    username text NOT NULL,
    last_seen_at timestamptz,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'deprovisioned')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz
);

COMMENT ON TABLE spine_identity.user_link IS 'Bridge: Keycloak OIDC sub ↔ internal Spine user_id. Created on first login.';
COMMENT ON COLUMN spine_identity.user_link.keycloak_sub IS 'OIDC sub claim (Keycloak subject UUID); unique.';
COMMENT ON COLUMN spine_identity.user_link.internal_user_id IS 'Internal Spine user UUID; FK target across other schemas.';
COMMENT ON COLUMN spine_identity.user_link.email IS 'Email from Keycloak; refreshed on token exchange.';
COMMENT ON COLUMN spine_identity.user_link.username IS 'Preferred username from Keycloak.';
COMMENT ON COLUMN spine_identity.user_link.last_seen_at IS 'Last successful auth event timestamp.';
COMMENT ON COLUMN spine_identity.user_link.status IS 'active | suspended | deprovisioned.';

CREATE TRIGGER trg_user_link_touch BEFORE UPDATE ON spine_identity.user_link
FOR EACH ROW EXECUTE FUNCTION public._touch_updated_at();

CREATE INDEX idx_user_link_email ON spine_identity.user_link (email);
CREATE INDEX idx_user_link_username ON spine_identity.user_link (username);
CREATE INDEX idx_user_link_status ON spine_identity.user_link (status);
CREATE INDEX idx_user_link_last_seen_at ON spine_identity.user_link (last_seen_at);

-- ─────────────────────────────────────────────────────────────────────
-- group_role_mapping — Keycloak group path → Spine internal role
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_identity.group_role_mapping (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    keycloak_group text NOT NULL,
    internal_role text NOT NULL,
    bundle_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz,
    CONSTRAINT fk_group_role_bundle FOREIGN KEY (bundle_id) REFERENCES spine_license.bundle (id) ON DELETE SET NULL,
    CONSTRAINT uq_group_role_mapping UNIQUE (keycloak_group, internal_role, bundle_id)
);

COMMENT ON TABLE spine_identity.group_role_mapping IS 'Keycloak group → Spine role mapping; bundle_id NULL = global.';
COMMENT ON COLUMN spine_identity.group_role_mapping.keycloak_group IS 'Keycloak group path from token groups claim (e.g. /spine-admins).';
COMMENT ON COLUMN spine_identity.group_role_mapping.internal_role IS 'Spine role: conductor | engineer | operator | planner | qa | architect | product | devops | etc.';
COMMENT ON COLUMN spine_identity.group_role_mapping.bundle_id IS 'License bundle scope; NULL = global mapping.';

CREATE TRIGGER trg_group_role_mapping_touch BEFORE UPDATE ON spine_identity.group_role_mapping
FOR EACH ROW EXECUTE FUNCTION public._touch_updated_at();

CREATE INDEX idx_group_role_keycloak_group ON spine_identity.group_role_mapping (keycloak_group);
CREATE INDEX idx_group_role_internal_role ON spine_identity.group_role_mapping (internal_role);
CREATE INDEX idx_group_role_bundle_id ON spine_identity.group_role_mapping (bundle_id);

-- ─────────────────────────────────────────────────────────────────────
-- session_audit — append-only auth event log
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_identity.session_audit (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    action text NOT NULL,
    ip inet,
    ua text,
    ts timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_session_audit_user FOREIGN KEY (user_id) REFERENCES spine_identity.user_link (id) ON DELETE RESTRICT
);

COMMENT ON TABLE spine_identity.session_audit IS 'Append-only auth event log. NEVER UPDATE; retention at storage layer.';
COMMENT ON COLUMN spine_identity.session_audit.user_id IS 'spine_identity.user_link.id.';
COMMENT ON COLUMN spine_identity.session_audit.action IS 'login | logout | token_refresh | mfa_challenge | role_elevation | account_suspended.';
COMMENT ON COLUMN spine_identity.session_audit.ip IS 'Client IP (inet for subnet queries); NULL for service-account.';
COMMENT ON COLUMN spine_identity.session_audit.ua IS 'User-Agent string; NULL for CLI/service-account.';
COMMENT ON COLUMN spine_identity.session_audit.ts IS 'Authoritative event timestamp.';

CREATE INDEX idx_session_audit_user_id ON spine_identity.session_audit (user_id);
CREATE INDEX idx_session_audit_action ON spine_identity.session_audit (action);
CREATE INDEX idx_session_audit_ts ON spine_identity.session_audit (ts DESC);
CREATE INDEX idx_session_audit_ip ON spine_identity.session_audit (ip);
