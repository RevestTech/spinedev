-- V29: Smart Spine 3-tier learning — Design Decision #27.
-- Lessons with vector embeddings + scope policy + anonymized cross-org telemetry.

CREATE SCHEMA IF NOT EXISTS spine_learning;
CREATE EXTENSION IF NOT EXISTS vector;  -- pgvector

COMMENT ON SCHEMA spine_learning IS
'Smart Spine 3-tier learning: project / within_hub / cross_org with embeddings.';

-- ─────────────────────────────────────────────────────────────────────
-- ENUM: lesson_scope — 3 tiers
-- ─────────────────────────────────────────────────────────────────────

DO $$ BEGIN
    CREATE TYPE spine_learning.lesson_scope AS ENUM ('project','within_hub','cross_org');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

COMMENT ON TYPE spine_learning.lesson_scope IS '3-tier learning visibility scope per #27.';

-- ─────────────────────────────────────────────────────────────────────
-- lesson — embedded lessons for semantic retrieval
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_learning.lesson (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    scope spine_learning.lesson_scope NOT NULL DEFAULT 'project',
    source_audit_record_id uuid,
    lesson_text text NOT NULL,
    embedding vector(1536),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz
);

COMMENT ON TABLE spine_learning.lesson IS 'Learned lessons with pgvector embeddings for semantic retrieval. scope controls visibility.';
COMMENT ON COLUMN spine_learning.lesson.scope IS 'project | within_hub | cross_org.';
COMMENT ON COLUMN spine_learning.lesson.source_audit_record_id IS 'spine_audit.audit_record.id; FK enforced in Wave 1.';
COMMENT ON COLUMN spine_learning.lesson.lesson_text IS 'Embedded lesson content.';
COMMENT ON COLUMN spine_learning.lesson.embedding IS 'vector(1536) — text-embedding-3-small compatible. Wave 1 may reconcile to 768 to match V2 spine_kg.';

CREATE TRIGGER trg_lesson_touch BEFORE UPDATE ON spine_learning.lesson
FOR EACH ROW EXECUTE FUNCTION public._touch_updated_at();

CREATE INDEX idx_lesson_scope ON spine_learning.lesson (scope);
CREATE INDEX idx_lesson_created_at ON spine_learning.lesson (created_at DESC);
CREATE INDEX idx_lesson_embedding ON spine_learning.lesson USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ─────────────────────────────────────────────────────────────────────
-- scope_policy — per-hub or per-project tier enablement
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_learning.scope_policy (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    hub_id uuid,
    project_id uuid,
    within_hub_enabled boolean NOT NULL DEFAULT TRUE,
    cross_org_consent boolean NOT NULL DEFAULT FALSE,
    granular_consent_jsonb jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz,
    CONSTRAINT uq_scope_policy_hub_project UNIQUE (hub_id, project_id)
);

COMMENT ON TABLE spine_learning.scope_policy IS 'Per-hub/project tier policy; defaults: within_hub ON, cross_org OFF per #27.';
COMMENT ON COLUMN spine_learning.scope_policy.hub_id IS 'Hub scope; NULL = global default. FK to spine_federation.hub in Wave 1.';
COMMENT ON COLUMN spine_learning.scope_policy.project_id IS 'Project override; NULL = hub-wide. FK to spine_hub.project in Wave 1.';
COMMENT ON COLUMN spine_learning.scope_policy.within_hub_enabled IS 'Cross-project sharing within the same hub. Default true.';
COMMENT ON COLUMN spine_learning.scope_policy.cross_org_consent IS 'Cross-org sharing with federated hubs. Default false (opt-in).';
COMMENT ON COLUMN spine_learning.scope_policy.granular_consent_jsonb IS 'Per-category consent overrides; schema is category-specific.';

CREATE TRIGGER trg_scope_policy_touch BEFORE UPDATE ON spine_learning.scope_policy
FOR EACH ROW EXECUTE FUNCTION public._touch_updated_at();

CREATE INDEX idx_scope_policy_hub_id ON spine_learning.scope_policy (hub_id);
CREATE INDEX idx_scope_policy_project_id ON spine_learning.scope_policy (project_id);

-- ─────────────────────────────────────────────────────────────────────
-- telemetry_anonymized — aggregate cross-org telemetry, no PII
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_learning.telemetry_anonymized (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    pattern_class text NOT NULL,
    count bigint NOT NULL DEFAULT 0 CHECK (count >= 0),
    period text NOT NULL,
    anonymization_method text NOT NULL,
    exported_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz
);

COMMENT ON TABLE spine_learning.telemetry_anonymized IS 'Aggregate cross-org pattern telemetry. NO PII, NO project/user data.';
COMMENT ON COLUMN spine_learning.telemetry_anonymized.pattern_class IS 'Pattern semantic class (e.g. late_qa_gate, repeated_rollback).';
COMMENT ON COLUMN spine_learning.telemetry_anonymized.count IS 'Occurrences within the period.';
COMMENT ON COLUMN spine_learning.telemetry_anonymized.period IS 'ISO 8601 period string (e.g. 2026-05).';
COMMENT ON COLUMN spine_learning.telemetry_anonymized.anonymization_method IS 'k_anonymity_N | differential_privacy_epsX | synthetic.';
COMMENT ON COLUMN spine_learning.telemetry_anonymized.exported_at IS 'Last successful cross-org export; NULL = never.';

CREATE TRIGGER trg_telemetry_anonymized_touch BEFORE UPDATE ON spine_learning.telemetry_anonymized
FOR EACH ROW EXECUTE FUNCTION public._touch_updated_at();

CREATE INDEX idx_telemetry_pattern_class ON spine_learning.telemetry_anonymized (pattern_class);
CREATE INDEX idx_telemetry_period ON spine_learning.telemetry_anonymized (period);
CREATE INDEX idx_telemetry_exported_at ON spine_learning.telemetry_anonymized (exported_at);
