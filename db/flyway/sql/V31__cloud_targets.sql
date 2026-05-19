-- V31: Cloud targets — Design Decisions #17, #20.
-- BYOC and customer-cloud accounts + deployed Hub instances across 4 deployment shapes.

CREATE SCHEMA IF NOT EXISTS spine_cloud;

COMMENT ON SCHEMA spine_cloud IS
'BYOC + customer-cloud account registry; deployed Hub instances across 4 deployment shapes.';

-- ─────────────────────────────────────────────────────────────────────
-- ENUMs: cloud_provider, deployment_shape
-- ─────────────────────────────────────────────────────────────────────

DO $$ BEGIN
    CREATE TYPE spine_cloud.cloud_provider AS ENUM ('aws','azure','gcp','railway','fly','do','onprem');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE spine_cloud.deployment_shape AS ENUM ('laptop','byoc','customer_cloud','onprem');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

COMMENT ON TYPE spine_cloud.cloud_provider IS 'Cloud target: aws | azure | gcp | railway | fly | do | onprem per #20.';
COMMENT ON TYPE spine_cloud.deployment_shape IS '4 deployment shapes per #17.';

-- ─────────────────────────────────────────────────────────────────────
-- target_account — customer cloud account registered for BYOC
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_cloud.target_account (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id text NOT NULL,
    cloud spine_cloud.cloud_provider NOT NULL,
    account_ref text NOT NULL,
    delegated_role_arn text,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'decommissioned')),
    registered_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz,
    CONSTRAINT uq_target_account UNIQUE (customer_id, cloud, account_ref)
);

COMMENT ON TABLE spine_cloud.target_account IS 'Customer cloud accounts registered for BYOC. delegated_role_arn for AWS cross-account IAM.';
COMMENT ON COLUMN spine_cloud.target_account.customer_id IS 'Customer identifier; aligns with spine_license.bundle.customer.';
COMMENT ON COLUMN spine_cloud.target_account.cloud IS 'Cloud provider.';
COMMENT ON COLUMN spine_cloud.target_account.account_ref IS 'Cloud-native account ID (AWS account ID / GCP project / Azure subscription).';
COMMENT ON COLUMN spine_cloud.target_account.delegated_role_arn IS 'AWS IAM Role ARN for cross-account delegation; NULL for non-AWS.';
COMMENT ON COLUMN spine_cloud.target_account.status IS 'active | suspended | decommissioned.';
COMMENT ON COLUMN spine_cloud.target_account.registered_at IS 'First registration timestamp.';

CREATE TRIGGER trg_target_account_touch BEFORE UPDATE ON spine_cloud.target_account
FOR EACH ROW EXECUTE FUNCTION public._touch_updated_at();

CREATE INDEX idx_target_account_customer_id ON spine_cloud.target_account (customer_id);
CREATE INDEX idx_target_account_cloud ON spine_cloud.target_account (cloud);
CREATE INDEX idx_target_account_status ON spine_cloud.target_account (status);

-- ─────────────────────────────────────────────────────────────────────
-- deployed_hub — Hub instances deployed to target accounts
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_cloud.deployed_hub (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    target_account_id uuid NOT NULL,
    deployment_shape spine_cloud.deployment_shape NOT NULL,
    hub_url text,
    version text NOT NULL,
    provisioned_at timestamptz NOT NULL DEFAULT now(),
    decommissioned_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz,
    CONSTRAINT fk_deployed_hub_target FOREIGN KEY (target_account_id) REFERENCES spine_cloud.target_account (id) ON DELETE RESTRICT
);

COMMENT ON TABLE spine_cloud.deployed_hub IS 'Hub instances deployed to registered cloud targets.';
COMMENT ON COLUMN spine_cloud.deployed_hub.target_account_id IS 'Cloud account this hub is deployed into.';
COMMENT ON COLUMN spine_cloud.deployed_hub.deployment_shape IS 'laptop | byoc | customer_cloud | onprem.';
COMMENT ON COLUMN spine_cloud.deployed_hub.hub_url IS 'Public HTTPS base URL; NULL for private/local.';
COMMENT ON COLUMN spine_cloud.deployed_hub.version IS 'Spine version string running on this hub.';
COMMENT ON COLUMN spine_cloud.deployed_hub.provisioned_at IS 'Provisioning timestamp.';
COMMENT ON COLUMN spine_cloud.deployed_hub.decommissioned_at IS 'Teardown timestamp; NULL = active.';

CREATE TRIGGER trg_deployed_hub_touch BEFORE UPDATE ON spine_cloud.deployed_hub
FOR EACH ROW EXECUTE FUNCTION public._touch_updated_at();

CREATE INDEX idx_deployed_hub_target_account_id ON spine_cloud.deployed_hub (target_account_id);
CREATE INDEX idx_deployed_hub_deployment_shape ON spine_cloud.deployed_hub (deployment_shape);
CREATE INDEX idx_deployed_hub_version ON spine_cloud.deployed_hub (version);
CREATE INDEX idx_deployed_hub_decommissioned_at ON spine_cloud.deployed_hub (decommissioned_at);
