-- V22: Feature-flag licensing — Design Decision #23.
-- Signed license bundles + per-flag enablement + quota usage ledger.
-- Also defines the shared public._touch_updated_at() function reused by V23-V32.

CREATE SCHEMA IF NOT EXISTS spine_license;
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid()

COMMENT ON SCHEMA spine_license IS
'Feature-flag licensing registry. Signed bundles, per-flag enablement, quota ledger.';

-- ─────────────────────────────────────────────────────────────────────
-- Shared updated_at touch function (defined once; reused by V22-V32+)
-- ─────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public._touch_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION public._touch_updated_at() IS
'Shared trigger function setting updated_at = now() on UPDATE. Defined V22; reused V23+.';

-- ─────────────────────────────────────────────────────────────────────
-- bundle — one signed license per customer
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_license.bundle (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer TEXT NOT NULL,
    tier TEXT NOT NULL CHECK (tier IN ('free', 'founder', 'team', 'enterprise', 'airgapped', 'custom')),
    signed_payload BYTEA NOT NULL,
    signature BYTEA NOT NULL,
    signing_key_fingerprint TEXT NOT NULL,
    issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    audit_chain_anchor BYTEA,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ
);

COMMENT ON TABLE spine_license.bundle IS 'Signed license bundle per customer; supports offline verification.';
COMMENT ON COLUMN spine_license.bundle.customer IS 'Customer identifier.';
COMMENT ON COLUMN spine_license.bundle.tier IS 'License tier: free | founder | team | enterprise | airgapped | custom.';
COMMENT ON COLUMN spine_license.bundle.signed_payload IS 'Canonical JSON payload (raw bytes) covered by signature.';
COMMENT ON COLUMN spine_license.bundle.signature IS 'Ed25519 detached signature over signed_payload.';
COMMENT ON COLUMN spine_license.bundle.signing_key_fingerprint IS 'Hex SHA-256 fingerprint of vendor signing public key.';
COMMENT ON COLUMN spine_license.bundle.issued_at IS 'Issuance timestamp.';
COMMENT ON COLUMN spine_license.bundle.expires_at IS 'Expiry; NULL = perpetual.';
COMMENT ON COLUMN spine_license.bundle.revoked_at IS 'Revocation timestamp; NULL = active.';
COMMENT ON COLUMN spine_license.bundle.audit_chain_anchor IS 'SHA-256 of audit_record for issuance. TODO: FK to spine_audit in Wave 1.';

CREATE TRIGGER trg_bundle_touch BEFORE UPDATE ON spine_license.bundle
FOR EACH ROW EXECUTE FUNCTION public._touch_updated_at();

CREATE INDEX idx_bundle_customer ON spine_license.bundle (customer);
CREATE INDEX idx_bundle_tier ON spine_license.bundle (tier);
CREATE INDEX idx_bundle_expires_at ON spine_license.bundle (expires_at);
CREATE INDEX idx_bundle_revoked_at ON spine_license.bundle (revoked_at);

-- ─────────────────────────────────────────────────────────────────────
-- feature_flag — per-flag capability within a bundle
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_license.feature_flag (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bundle_id UUID NOT NULL,
    flag_name TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    quota_value BIGINT CHECK (quota_value IS NULL OR quota_value >= 0),
    quota_unit TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ,
    CONSTRAINT fk_feature_flag_bundle FOREIGN KEY (bundle_id) REFERENCES spine_license.bundle (id) ON DELETE CASCADE,
    CONSTRAINT uq_feature_flag_bundle_name UNIQUE (bundle_id, flag_name)
);

COMMENT ON TABLE spine_license.feature_flag IS 'Per-flag capability rows under a license bundle. Read by every feature gate.';
COMMENT ON COLUMN spine_license.feature_flag.bundle_id IS 'Parent license bundle.';
COMMENT ON COLUMN spine_license.feature_flag.flag_name IS 'Stable feature identifier (e.g. federation, devops_role, smart_spine).';
COMMENT ON COLUMN spine_license.feature_flag.enabled IS 'Whether the feature is on for this bundle.';
COMMENT ON COLUMN spine_license.feature_flag.quota_value IS 'Numeric ceiling for metered features; NULL = unlimited.';
COMMENT ON COLUMN spine_license.feature_flag.quota_unit IS 'Quota unit: agents_per_month | projects | seats | tokens_per_day.';

CREATE TRIGGER trg_feature_flag_touch BEFORE UPDATE ON spine_license.feature_flag
FOR EACH ROW EXECUTE FUNCTION public._touch_updated_at();

CREATE INDEX idx_feature_flag_bundle_id ON spine_license.feature_flag (bundle_id);
CREATE INDEX idx_feature_flag_flag_name ON spine_license.feature_flag (flag_name);
CREATE INDEX idx_feature_flag_enabled ON spine_license.feature_flag (enabled);

-- ─────────────────────────────────────────────────────────────────────
-- quota_usage — hash-chained per-period usage ledger
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_license.quota_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    flag_name TEXT NOT NULL,
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    used_value BIGINT NOT NULL DEFAULT 0 CHECK (used_value >= 0),
    ledger_anchor BYTEA,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ,
    CONSTRAINT chk_quota_period CHECK (period_end > period_start)
);

COMMENT ON TABLE spine_license.quota_usage IS 'Metered usage accumulator per flag per billing period; hash-chained for tamper detection.';
COMMENT ON COLUMN spine_license.quota_usage.flag_name IS 'Feature flag identifier matching spine_license.feature_flag.flag_name.';
COMMENT ON COLUMN spine_license.quota_usage.period_start IS 'Inclusive period start.';
COMMENT ON COLUMN spine_license.quota_usage.period_end IS 'Exclusive period end.';
COMMENT ON COLUMN spine_license.quota_usage.used_value IS 'Accumulated usage units within the period.';
COMMENT ON COLUMN spine_license.quota_usage.ledger_anchor IS 'SHA-256 of prior period row; NULL for chain bootstrap.';

CREATE TRIGGER trg_quota_usage_touch BEFORE UPDATE ON spine_license.quota_usage
FOR EACH ROW EXECUTE FUNCTION public._touch_updated_at();

CREATE INDEX idx_quota_usage_flag_name ON spine_license.quota_usage (flag_name);
CREATE INDEX idx_quota_usage_period_start ON spine_license.quota_usage (period_start);
