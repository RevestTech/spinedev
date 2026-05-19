-- V21: Spine Verify schemas — INIT-8 EPIC-8.3 STORY-8.3.1.
-- Ports TRON's Alembic baseline (verify/alembic/versions/001..008) into Flyway.
-- NOT duplicated here (per db/migration-survey.md): tron.llm_usage/llm_cost_*
-- → spine_recording (V16); tron.projects core → spine_lifecycle.project (V14);
-- tron.projects JSONB blobs → spine_lifecycle.project.metadata; tron.standards
-- → shared/standards/. TRON code-side migration follows in a separate story.
-- Numbering: spec said V20; that slot is taken by V20__spine_memory_schema
-- (STORY-4.2). This file lands at V21. See db/V21__spine_verify_schemas.README.md.

BEGIN;

CREATE SCHEMA IF NOT EXISTS spine_verify_audit;
CREATE SCHEMA IF NOT EXISTS spine_verify_threat_intel;
COMMENT ON SCHEMA spine_verify_audit IS 'TRON verify-internal: audit_run, finding, code_file, agent_metrics, cross_validation, api_key.';
COMMENT ON SCHEMA spine_verify_threat_intel IS 'Normalized advisories (CVE/GHSA/OSV) consumed by verify.';

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Enums mirror verify/tron/schemas/verification.py.
CREATE TYPE spine_verify_audit.vulnerability_type AS ENUM (
    'sql_injection', 'xss', 'hardcoded_secrets', 'insecure_deserialization', 'broken_auth',
    'security_misconfiguration', 'ssrf', 'path_traversal', 'command_injection',
    'open_redirect', 'insufficient_logging', 'dependency_vulnerability', 'other'
);
CREATE TYPE spine_verify_audit.severity_level AS ENUM ('critical', 'high', 'medium', 'low', 'info');
CREATE TYPE spine_verify_audit.cross_validation_status AS ENUM ('pending', 'confirmed', 'disputed', 'needs_review');
CREATE TYPE spine_verify_audit.consensus_level AS ENUM ('confirmed', 'disputed', 'primary_only', 'validator_only');
CREATE TYPE spine_verify_audit.audit_run_status AS ENUM ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'timeout');
CREATE TYPE spine_verify_audit.execution_outcome AS ENUM
('success', 'failure', 'timeout', 'resource_exceeded', 'sandbox_error', 'skipped');

-- audit_run — Alembic 001 (tron.audit_runs) + 008 (threat_intel_alerts_json
-- absorbed into metadata JSONB). project_id BIGINT is advisory — code populates
-- it; no DB-level FK to spine_lifecycle yet.
CREATE TABLE spine_verify_audit.audit_run (
    id bigserial PRIMARY KEY,
    audit_run_uuid uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    project_uuid uuid NOT NULL,
    project_id bigint,
    workflow_id text NOT NULL,
    workflow_run_id text NOT NULL,
    commit_hash text,
    branch text,
    trigger_type text,
    triggered_by text,
    status spine_verify_audit.audit_run_status NOT NULL DEFAULT 'queued',
    progress integer NOT NULL DEFAULT 0,
    quality_score numeric(5, 2),
    findings_total integer NOT NULL DEFAULT 0,
    findings_critical integer NOT NULL DEFAULT 0,
    findings_high integer NOT NULL DEFAULT 0,
    findings_medium integer NOT NULL DEFAULT 0,
    findings_low integer NOT NULL DEFAULT 0,
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    error_message text,
    error_stack text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT audit_run_progress_chk CHECK (progress BETWEEN 0 AND 100)
);
CREATE INDEX idx_audit_run_project ON spine_verify_audit.audit_run (project_uuid, created_at DESC);
CREATE INDEX idx_audit_run_status ON spine_verify_audit.audit_run (status, created_at DESC);
CREATE INDEX idx_audit_run_workflow ON spine_verify_audit.audit_run (workflow_id);
CREATE INDEX idx_audit_run_meta_gin ON spine_verify_audit.audit_run USING gin (metadata);
COMMENT ON COLUMN spine_verify_audit.audit_run.project_id IS 'Advisory FK to spine_lifecycle.project(id); populated by app, no DB-level FK yet.';
COMMENT ON COLUMN spine_verify_audit.audit_run.metadata IS 'Absorbs former tron.audit_runs.threat_intel_alerts_json + ad-hoc fields.';

-- code_file — verify-local mirror of spine_kg.kg_node (full convergence later).
CREATE TABLE spine_verify_audit.code_file (
    id bigserial PRIMARY KEY,
    code_file_uuid uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    project_uuid uuid NOT NULL,
    file_path text NOT NULL,
    file_hash text NOT NULL,
    language text,
    file_type text,
    lines_of_code integer,
    complexity_score integer,
    directory_path text,
    dependency_count integer NOT NULL DEFAULT 0,
    dependent_count integer NOT NULL DEFAULT 0,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_code_file_project_path UNIQUE (project_uuid, file_path)
);
CREATE INDEX idx_code_file_project ON spine_verify_audit.code_file (project_uuid);
CREATE INDEX idx_code_file_hash ON spine_verify_audit.code_file (file_hash);
CREATE INDEX idx_code_file_path_trgm ON spine_verify_audit.code_file USING gin (file_path gin_trgm_ops);

-- finding — produced by ISO agents; FK within schema.
CREATE TABLE spine_verify_audit.finding (
    id bigserial PRIMARY KEY,
    finding_uuid uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    audit_run_id bigint NOT NULL REFERENCES spine_verify_audit.audit_run (id) ON DELETE CASCADE,
    project_uuid uuid NOT NULL,
    fingerprint text NOT NULL,
    rule_id text NOT NULL,
    vulnerability_type spine_verify_audit.vulnerability_type,
    file_path text NOT NULL,
    file_id bigint REFERENCES spine_verify_audit.code_file (id) ON DELETE SET NULL,
    line_start integer,
    line_end integer,
    column_start integer,
    column_end integer,
    severity spine_verify_audit.severity_level NOT NULL,
    category text,
    title text NOT NULL,
    description text NOT NULL,
    suggested_fix text,
    status text NOT NULL DEFAULT 'open',
    cross_validation_status spine_verify_audit.cross_validation_status NOT NULL DEFAULT 'pending',
    resolution text,
    resolved_at timestamptz,
    resolved_by text,
    code_snippet text,
    confidence numeric(6, 4),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT finding_confidence_chk CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1)
);
CREATE INDEX idx_finding_audit_run ON spine_verify_audit.finding (audit_run_id);
CREATE INDEX idx_finding_project_sev ON spine_verify_audit.finding (project_uuid, severity, created_at DESC);
CREATE INDEX idx_finding_fingerprint ON spine_verify_audit.finding (fingerprint, project_uuid);
CREATE INDEX idx_finding_open ON spine_verify_audit.finding (project_uuid, severity, created_at DESC) WHERE status = 'open';
CREATE INDEX idx_finding_search ON spine_verify_audit.finding USING gin (to_tsvector('english', title || ' ' || description));

-- finding_relationship — graph edges between findings.
CREATE TABLE spine_verify_audit.finding_relationship (
    id bigserial PRIMARY KEY,
    finding_id bigint NOT NULL REFERENCES spine_verify_audit.finding (id) ON DELETE CASCADE,
    related_finding_id bigint NOT NULL REFERENCES spine_verify_audit.finding (id) ON DELETE CASCADE,
    relationship_type text NOT NULL,
    confidence numeric(3, 2),
    detected_by text,
    reason text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_finding_rel UNIQUE (finding_id, related_finding_id, relationship_type),
    CONSTRAINT finding_rel_no_self_chk CHECK (finding_id <> related_finding_id),
    CONSTRAINT finding_rel_conf_chk CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1)
);

-- file_dependency — verify-local mirror of spine_kg.kg_edge.
CREATE TABLE spine_verify_audit.file_dependency (
    id bigserial PRIMARY KEY,
    source_file_id bigint NOT NULL REFERENCES spine_verify_audit.code_file (id) ON DELETE CASCADE,
    target_file_id bigint NOT NULL REFERENCES spine_verify_audit.code_file (id) ON DELETE CASCADE,
    dependency_type text NOT NULL,
    import_statement text,
    is_external boolean NOT NULL DEFAULT FALSE,
    is_circular boolean NOT NULL DEFAULT FALSE,
    usage_count integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_file_dep UNIQUE (source_file_id, target_file_id, dependency_type),
    CONSTRAINT file_dep_no_self_chk CHECK (source_file_id <> target_file_id)
);

-- agent_metrics — per-agent accounting (cost is mirrored to spine_recording by app).
CREATE TABLE spine_verify_audit.agent_metrics (
    id bigserial PRIMARY KEY,
    audit_run_id bigint NOT NULL REFERENCES spine_verify_audit.audit_run (id) ON DELETE CASCADE,
    agent_name text NOT NULL,
    provider text NOT NULL,
    model text NOT NULL,
    prompt_tokens integer NOT NULL DEFAULT 0,
    completion_tokens integer NOT NULL DEFAULT 0,
    cost_usd numeric(10, 6) NOT NULL DEFAULT 0,
    duration_ms integer NOT NULL DEFAULT 0,
    outcome spine_verify_audit.execution_outcome NOT NULL DEFAULT 'success',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT agent_metrics_tokens_chk CHECK (prompt_tokens >= 0 AND completion_tokens >= 0),
    CONSTRAINT agent_metrics_cost_chk CHECK (cost_usd >= 0),
    CONSTRAINT agent_metrics_dur_chk CHECK (duration_ms >= 0)
);
CREATE INDEX idx_agent_metrics_run ON spine_verify_audit.agent_metrics (audit_run_id);
CREATE INDEX idx_agent_metrics_agent ON spine_verify_audit.agent_metrics (agent_name, created_at DESC);

-- cross_validation — multi-LLM consensus rows tied to findings.
CREATE TABLE spine_verify_audit.cross_validation (
    id bigserial PRIMARY KEY,
    finding_id bigint NOT NULL REFERENCES spine_verify_audit.finding (id) ON DELETE CASCADE,
    primary_agent text NOT NULL,
    validator_agent text NOT NULL,
    consensus spine_verify_audit.consensus_level NOT NULL,
    primary_confidence numeric(6, 4),
    validator_confidence numeric(6, 4),
    rationale text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT xv_primary_conf_chk CHECK (primary_confidence IS NULL OR primary_confidence BETWEEN 0 AND 1),
    CONSTRAINT xv_validator_conf_chk CHECK (validator_confidence IS NULL OR validator_confidence BETWEEN 0 AND 1)
);
CREATE INDEX idx_xv_finding ON spine_verify_audit.cross_validation (finding_id);
CREATE INDEX idx_xv_consensus ON spine_verify_audit.cross_validation (consensus, created_at DESC);

-- api_key — verify-scoped (Alembic 005). Spine-wide auth is a separate story.
CREATE TABLE spine_verify_audit.api_key (
    id bigserial PRIMARY KEY,
    api_key_uuid uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    label text NOT NULL,
    key_hash text NOT NULL UNIQUE,
    scopes jsonb NOT NULL DEFAULT '["*"]'::jsonb,
    active boolean NOT NULL DEFAULT TRUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    revoked_at timestamptz
);
CREATE INDEX idx_api_key_active ON spine_verify_audit.api_key (active);

-- advisory — normalized threat-intel; per-run snapshot stays in audit_run.metadata.
CREATE TABLE spine_verify_threat_intel.advisory (
    id bigserial PRIMARY KEY,
    advisory_uuid uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    source text NOT NULL,
    external_id text NOT NULL,
    severity spine_verify_audit.severity_level NOT NULL,
    title text NOT NULL,
    summary text,
    affected_package text,
    affected_versions text,
    fixed_versions text,
    references_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    published_at timestamptz,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_advisory_source_external UNIQUE (source, external_id)
);
CREATE INDEX idx_advisory_severity ON spine_verify_threat_intel.advisory (severity, ingested_at DESC);
CREATE INDEX idx_advisory_package ON spine_verify_threat_intel.advisory (affected_package);
CREATE INDEX idx_advisory_refs_gin ON spine_verify_threat_intel.advisory USING gin (references_json);
COMMENT ON TABLE spine_verify_threat_intel.advisory IS 'Normalized CVE/GHSA/OSV rows from threat-intel ingestion (FR-3).';

COMMIT;
