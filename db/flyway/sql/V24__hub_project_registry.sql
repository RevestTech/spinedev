-- V24: Hub-as-product project enumeration — Design Decisions #3, #19.
-- Project lifecycle + RBAC membership + extensible key/value metadata.

CREATE SCHEMA IF NOT EXISTS spine_hub;

COMMENT ON SCHEMA spine_hub IS
'Hub-managed projects: lifecycle, RBAC membership, extensible metadata.';

-- ─────────────────────────────────────────────────────────────────────
-- project — projects hosted on or rooted to a Hub
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_hub.project (
    id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    hub_id            uuid        NOT NULL,
    name              text        NOT NULL,
    work_item_type    text        NOT NULL DEFAULT 'feature'
                                  CHECK (work_item_type IN ('feature','bug','incident','support','refactor','infra','compliance')),
    owner_user_id     uuid,
    federation_origin text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    archived_at       timestamptz,
    updated_at        timestamptz,
    CONSTRAINT fk_hub_project_hub FOREIGN KEY (hub_id) REFERENCES spine_federation.hub (hub_id) ON DELETE RESTRICT
);

COMMENT ON TABLE  spine_hub.project IS 'Projects hosted on a hub. work_item_type drives intake template + default role set.';
COMMENT ON COLUMN spine_hub.project.hub_id            IS 'Owning hub.';
COMMENT ON COLUMN spine_hub.project.name              IS 'Display name; uniqueness enforced at app layer per hub.';
COMMENT ON COLUMN spine_hub.project.work_item_type    IS 'Primary work-item type per #19.';
COMMENT ON COLUMN spine_hub.project.owner_user_id     IS 'spine_identity.user_link.id; FK enforced in Wave 1.';
COMMENT ON COLUMN spine_hub.project.federation_origin IS 'hub_id of origin hub when project federated in; NULL for local.';
COMMENT ON COLUMN spine_hub.project.created_at        IS 'Creation timestamp.';
COMMENT ON COLUMN spine_hub.project.archived_at       IS 'Soft-delete timestamp; NULL = active.';

CREATE TRIGGER trg_hub_project_touch BEFORE UPDATE ON spine_hub.project
    FOR EACH ROW EXECUTE FUNCTION public._touch_updated_at();

CREATE INDEX idx_hub_project_hub_id         ON spine_hub.project (hub_id);
CREATE INDEX idx_hub_project_work_item_type ON spine_hub.project (work_item_type);
CREATE INDEX idx_hub_project_owner_user_id  ON spine_hub.project (owner_user_id);
CREATE INDEX idx_hub_project_archived_at    ON spine_hub.project (archived_at);

-- ─────────────────────────────────────────────────────────────────────
-- project_membership — RBAC links users → projects
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_hub.project_membership (
    project_id uuid        NOT NULL,
    user_id    uuid        NOT NULL,
    role       text        NOT NULL,
    granted_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz,
    PRIMARY KEY (project_id, user_id),
    CONSTRAINT fk_membership_project FOREIGN KEY (project_id) REFERENCES spine_hub.project (id) ON DELETE CASCADE
);

COMMENT ON TABLE  spine_hub.project_membership IS 'User RBAC membership in projects. Composite PK; FK to spine_identity.user_link in Wave 1.';
COMMENT ON COLUMN spine_hub.project_membership.project_id IS 'Project.';
COMMENT ON COLUMN spine_hub.project_membership.user_id    IS 'spine_identity.user_link.id; FK enforced in Wave 1.';
COMMENT ON COLUMN spine_hub.project_membership.role       IS 'Named role: owner | contributor | viewer | conductor | auditor.';
COMMENT ON COLUMN spine_hub.project_membership.granted_at IS 'Grant timestamp.';

CREATE TRIGGER trg_project_membership_touch BEFORE UPDATE ON spine_hub.project_membership
    FOR EACH ROW EXECUTE FUNCTION public._touch_updated_at();

CREATE INDEX idx_project_membership_user_id ON spine_hub.project_membership (user_id);
CREATE INDEX idx_project_membership_role    ON spine_hub.project_membership (role);

-- ─────────────────────────────────────────────────────────────────────
-- project_metadata — extensible key/value
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_hub.project_metadata (
    project_id uuid        NOT NULL,
    key        text        NOT NULL,
    value      text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, key),
    CONSTRAINT fk_project_metadata_project FOREIGN KEY (project_id) REFERENCES spine_hub.project (id) ON DELETE CASCADE
);

COMMENT ON TABLE  spine_hub.project_metadata IS 'Key/value metadata per project. Namespace keys (e.g. github.repo_url) to avoid collisions.';
COMMENT ON COLUMN spine_hub.project_metadata.project_id IS 'Project.';
COMMENT ON COLUMN spine_hub.project_metadata.key        IS 'Namespaced metadata key (e.g. github.repo_url).';
COMMENT ON COLUMN spine_hub.project_metadata.value      IS 'String value; use JSON-encoded string for complex values.';

CREATE INDEX idx_project_metadata_project_id ON spine_hub.project_metadata (project_id);
CREATE INDEX idx_project_metadata_key        ON spine_hub.project_metadata (key);
