-- V28: Work-item type registry — Design Decision #19.
-- 7 canonical types + versioned intake templates + backfill ALTER on spine_lifecycle.project.

CREATE SCHEMA IF NOT EXISTS spine_workitem;

COMMENT ON SCHEMA spine_workitem IS
'7 canonical work-item types: feature/bug/incident/support/refactor/infra/compliance.';

-- ─────────────────────────────────────────────────────────────────────
-- ENUM: item_type — exactly 7
-- ─────────────────────────────────────────────────────────────────────

DO $$ BEGIN
    CREATE TYPE spine_workitem.item_type AS ENUM (
        'feature','bug','incident','support','refactor','infra','compliance'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

COMMENT ON TYPE spine_workitem.item_type IS '7 canonical work-item types per #19.';

-- ─────────────────────────────────────────────────────────────────────
-- type_registry — one row per type; type enum is natural PK
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_workitem.type_registry (
    type spine_workitem.item_type PRIMARY KEY,
    intake_template_path text NOT NULL,
    pipeline_id text NOT NULL,
    default_role_set jsonb NOT NULL DEFAULT '[]',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz
);

COMMENT ON TABLE spine_workitem.type_registry IS 'Per-type intake template + pipeline + default role set.';
COMMENT ON COLUMN spine_workitem.type_registry.type IS 'Work-item type enum value (natural PK).';
COMMENT ON COLUMN spine_workitem.type_registry.intake_template_path IS 'Org-bundle-relative path to intake YAML template.';
COMMENT ON COLUMN spine_workitem.type_registry.pipeline_id IS 'SDLC pipeline identifier.';
COMMENT ON COLUMN spine_workitem.type_registry.default_role_set IS 'JSON array of default Spine role names.';

CREATE TRIGGER trg_type_registry_touch BEFORE UPDATE ON spine_workitem.type_registry
FOR EACH ROW EXECUTE FUNCTION public._touch_updated_at();

-- Seed 7 canonical types
INSERT INTO spine_workitem.type_registry (type, intake_template_path, pipeline_id, default_role_set) VALUES
('feature', 'templates/intake/feature.yaml', 'default_feature_pipeline', '["product","planner","architect","engineer","qa"]'),
('bug', 'templates/intake/bug.yaml', 'default_bug_pipeline', '["engineer","qa"]'),
('incident', 'templates/intake/incident.yaml', 'default_incident_pipeline', '["operator","devops","engineer","conductor"]'),
('support', 'templates/intake/support.yaml', 'default_support_pipeline', '["customer_support","engineer"]'),
('refactor', 'templates/intake/refactor.yaml', 'default_refactor_pipeline', '["architect","engineer","qa"]'),
('infra', 'templates/intake/infra.yaml', 'default_infra_pipeline', '["devops","architect","security_engineer"]'),
('compliance', 'templates/intake/compliance.yaml', 'default_compliance_pipeline', '["compliance_officer","security_engineer","tech_writer"]')
ON CONFLICT (type) DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────
-- template_version — versioned intake templates for A/B + rollback
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_workitem.template_version (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    type spine_workitem.item_type NOT NULL,
    version text NOT NULL,
    template_yaml_hash bytea NOT NULL,
    active boolean NOT NULL DEFAULT FALSE,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz,
    CONSTRAINT uq_template_version UNIQUE (type, version)
);

COMMENT ON TABLE spine_workitem.template_version IS 'Versioned intake templates; only one per type should be active at a time.';
COMMENT ON COLUMN spine_workitem.template_version.type IS 'Work-item type.';
COMMENT ON COLUMN spine_workitem.template_version.version IS 'Semver string.';
COMMENT ON COLUMN spine_workitem.template_version.template_yaml_hash IS 'SHA-256 of canonical YAML bytes.';
COMMENT ON COLUMN spine_workitem.template_version.active IS 'Currently active template version for this type.';

CREATE TRIGGER trg_template_version_touch BEFORE UPDATE ON spine_workitem.template_version
FOR EACH ROW EXECUTE FUNCTION public._touch_updated_at();

CREATE INDEX idx_template_version_type ON spine_workitem.template_version (type);
CREATE INDEX idx_template_version_active ON spine_workitem.template_version (active) WHERE active = TRUE;

-- ─────────────────────────────────────────────────────────────────────
-- ALTER spine_lifecycle.project: add work_item_type column (idempotent)
-- ─────────────────────────────────────────────────────────────────────

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'spine_lifecycle' AND table_name = 'project'
    ) THEN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'spine_lifecycle' AND table_name = 'project' AND column_name = 'work_item_type'
        ) THEN
            ALTER TABLE spine_lifecycle.project
                ADD COLUMN work_item_type text NOT NULL DEFAULT 'feature'
                CHECK (work_item_type IN ('feature','bug','incident','support','refactor','infra','compliance'));

            COMMENT ON COLUMN spine_lifecycle.project.work_item_type IS
                'Primary work-item type added V28; backfilled to feature for pre-existing rows.';
        END IF;
    END IF;
END $$;
