-- V23: Hub federation registry — Design Decisions #4, #10, #16.
-- Parent/child Hub mesh + consent records + update distribution with approval cascade.

CREATE SCHEMA IF NOT EXISTS spine_federation;

COMMENT ON SCHEMA spine_federation IS
'Fractal Hub federation: hub registry, consent records, update distribution.';

-- ─────────────────────────────────────────────────────────────────────
-- hub — every hub known to the local hub (parents + children)
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_federation.hub (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    hub_id uuid NOT NULL UNIQUE,
    parent_hub_id uuid,
    name text NOT NULL,
    base_url text NOT NULL,
    public_key text NOT NULL,
    registered_at timestamptz NOT NULL DEFAULT now(),
    consent_status text NOT NULL DEFAULT 'pending' CHECK (consent_status IN ('pending', 'active', 'suspended', 'revoked')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz,
    CONSTRAINT fk_hub_parent FOREIGN KEY (parent_hub_id) REFERENCES spine_federation.hub (hub_id) ON DELETE SET NULL
);

COMMENT ON TABLE spine_federation.hub IS 'Hub registry; self-referencing parent_hub_id models federation hierarchy.';
COMMENT ON COLUMN spine_federation.hub.hub_id IS 'Globally unique hub UUID assigned at registration.';
COMMENT ON COLUMN spine_federation.hub.parent_hub_id IS 'Immediate parent hub_id; NULL for root.';
COMMENT ON COLUMN spine_federation.hub.name IS 'Human-readable display name.';
COMMENT ON COLUMN spine_federation.hub.base_url IS 'Canonical HTTPS base URL for API + update delivery.';
COMMENT ON COLUMN spine_federation.hub.public_key IS 'PEM-encoded Ed25519 or RSA public key for message verification.';
COMMENT ON COLUMN spine_federation.hub.registered_at IS 'First registration timestamp.';
COMMENT ON COLUMN spine_federation.hub.consent_status IS 'Lifecycle: pending | active | suspended | revoked.';

CREATE TRIGGER trg_hub_touch BEFORE UPDATE ON spine_federation.hub
FOR EACH ROW EXECUTE FUNCTION public._touch_updated_at();

CREATE INDEX idx_hub_parent_hub_id ON spine_federation.hub (parent_hub_id);
CREATE INDEX idx_hub_consent_status ON spine_federation.hub (consent_status);

-- ─────────────────────────────────────────────────────────────────────
-- consent_record — explicit consent grants child→parent
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_federation.consent_record (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    child_hub_id uuid NOT NULL,
    parent_hub_id uuid NOT NULL,
    consent_class text NOT NULL,
    granted_at timestamptz NOT NULL DEFAULT now(),
    granted_by text NOT NULL,
    scope_jsonb jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz,
    CONSTRAINT fk_consent_child FOREIGN KEY (child_hub_id) REFERENCES spine_federation.hub (hub_id) ON DELETE CASCADE,
    CONSTRAINT fk_consent_parent FOREIGN KEY (parent_hub_id) REFERENCES spine_federation.hub (hub_id) ON DELETE CASCADE
);

COMMENT ON TABLE spine_federation.consent_record IS 'Child→parent consent grants per consent_class with granular scope_jsonb.';
COMMENT ON COLUMN spine_federation.consent_record.child_hub_id IS 'Consenting child hub_id.';
COMMENT ON COLUMN spine_federation.consent_record.parent_hub_id IS 'Receiving parent hub_id.';
COMMENT ON COLUMN spine_federation.consent_record.consent_class IS 'Category: telemetry | update_push | learning_cross_org | audit_export.';
COMMENT ON COLUMN spine_federation.consent_record.granted_at IS 'Consent timestamp.';
COMMENT ON COLUMN spine_federation.consent_record.granted_by IS 'Identity (user / service-account) that approved.';
COMMENT ON COLUMN spine_federation.consent_record.scope_jsonb IS 'Fine-grained scope flags; schema is consent_class-specific.';

CREATE TRIGGER trg_consent_record_touch BEFORE UPDATE ON spine_federation.consent_record
FOR EACH ROW EXECUTE FUNCTION public._touch_updated_at();

CREATE INDEX idx_consent_child ON spine_federation.consent_record (child_hub_id);
CREATE INDEX idx_consent_parent ON spine_federation.consent_record (parent_hub_id);
CREATE INDEX idx_consent_consent_class ON spine_federation.consent_record (consent_class);

-- ─────────────────────────────────────────────────────────────────────
-- update_distribution — signed bundle rollout tracking
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_federation.update_distribution (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_hub_id uuid NOT NULL,
    target_hub_id uuid NOT NULL,
    bundle_version text NOT NULL,
    signature bytea NOT NULL,
    approved_at timestamptz,
    approved_by text,
    rollout_status text NOT NULL DEFAULT 'pending' CHECK (rollout_status IN ('pending', 'in_progress', 'completed', 'failed', 'rolled_back')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz,
    CONSTRAINT fk_update_source FOREIGN KEY (source_hub_id) REFERENCES spine_federation.hub (hub_id) ON DELETE RESTRICT,
    CONSTRAINT fk_update_target FOREIGN KEY (target_hub_id) REFERENCES spine_federation.hub (hub_id) ON DELETE RESTRICT
);

COMMENT ON TABLE spine_federation.update_distribution IS 'Signed bundle rollouts source→target with approval gate.';
COMMENT ON COLUMN spine_federation.update_distribution.source_hub_id IS 'Origin hub_id.';
COMMENT ON COLUMN spine_federation.update_distribution.target_hub_id IS 'Recipient hub_id.';
COMMENT ON COLUMN spine_federation.update_distribution.bundle_version IS 'Semver or hash-stamped bundle version string.';
COMMENT ON COLUMN spine_federation.update_distribution.signature IS 'Cryptographic signature over bundle payload; verified before apply.';
COMMENT ON COLUMN spine_federation.update_distribution.approved_at IS 'Approval timestamp; NULL = no approval required for this rollout.';
COMMENT ON COLUMN spine_federation.update_distribution.approved_by IS 'Identity that signed off.';
COMMENT ON COLUMN spine_federation.update_distribution.rollout_status IS 'pending | in_progress | completed | failed | rolled_back.';

CREATE TRIGGER trg_update_dist_touch BEFORE UPDATE ON spine_federation.update_distribution
FOR EACH ROW EXECUTE FUNCTION public._touch_updated_at();

CREATE INDEX idx_update_dist_source ON spine_federation.update_distribution (source_hub_id);
CREATE INDEX idx_update_dist_target ON spine_federation.update_distribution (target_hub_id);
CREATE INDEX idx_update_dist_rollout_status ON spine_federation.update_distribution (rollout_status);
CREATE INDEX idx_update_dist_bundle_version ON spine_federation.update_distribution (bundle_version);
