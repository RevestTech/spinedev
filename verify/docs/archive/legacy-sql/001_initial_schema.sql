-- Migration 001: Core Schema
-- Creates all core tables, indexes, triggers, and partitions
-- PostgreSQL 15+

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Helper function for updated_at triggers
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- EXTENSIONS
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS pgvector;
CREATE EXTENSION IF NOT EXISTS ltree;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- ============================================================================
-- CORE TABLES
-- ============================================================================

-- Projects table
CREATE TABLE projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    repo_url TEXT,
    default_branch VARCHAR(100) DEFAULT 'main',
    company_standards_version VARCHAR(50),
    project_standards_version VARCHAR(50),
    status VARCHAR(50) DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID,
    deleted_at TIMESTAMPTZ
);

CREATE INDEX idx_projects_status ON projects(status);
CREATE INDEX idx_projects_created_at ON projects(created_at);
CREATE INDEX idx_projects_updated_at ON projects(updated_at);

CREATE TRIGGER trigger_projects_updated_at
    BEFORE UPDATE ON projects
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Audit runs table (partitioned by created_at)
CREATE TABLE audit_runs (
    id UUID,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    workflow_id VARCHAR(255) NOT NULL,
    workflow_run_id VARCHAR(255) NOT NULL,
    commit_hash VARCHAR(64),
    branch VARCHAR(100),
    trigger_type VARCHAR(50),
    triggered_by UUID,
    status VARCHAR(50) DEFAULT 'running',
    progress INT CHECK (progress >= 0 AND progress <= 100),
    quality_score DECIMAL(5,2),
    findings_total INT DEFAULT 0,
    findings_critical INT DEFAULT 0,
    findings_high INT DEFAULT 0,
    findings_medium INT DEFAULT 0,
    findings_low INT DEFAULT 0,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    duration_seconds INT GENERATED ALWAYS AS (
        CASE 
            WHEN completed_at IS NOT NULL THEN EXTRACT(EPOCH FROM (completed_at - started_at))::INT
            ELSE NULL
        END
    ) STORED,
    error_message TEXT,
    error_stack TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

CREATE TABLE audit_runs_2026_04 PARTITION OF audit_runs
    FOR VALUES FROM ('2026-04-01'::TIMESTAMPTZ) TO ('2026-05-01'::TIMESTAMPTZ);

CREATE TABLE audit_runs_2026_05 PARTITION OF audit_runs
    FOR VALUES FROM ('2026-05-01'::TIMESTAMPTZ) TO ('2026-06-01'::TIMESTAMPTZ);

CREATE INDEX idx_audit_runs_project_created ON audit_runs(project_id, created_at);
CREATE INDEX idx_audit_runs_status_created ON audit_runs(status, created_at);
CREATE INDEX idx_audit_runs_workflow_id ON audit_runs(workflow_id);
CREATE INDEX idx_audit_runs_quality_score ON audit_runs(quality_score);

CREATE TRIGGER trigger_audit_runs_updated_at
    BEFORE UPDATE ON audit_runs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Findings table (partitioned by created_at)
CREATE TABLE findings (
    id UUID,
    audit_run_id UUID NOT NULL,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    fingerprint VARCHAR(64) NOT NULL,
    rule_id VARCHAR(255) NOT NULL,
    file_path TEXT NOT NULL,
    line_start INT,
    line_end INT,
    column_start INT,
    column_end INT,
    severity VARCHAR(20) NOT NULL,
    category VARCHAR(100),
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    suggested_fix TEXT,
    status VARCHAR(50) DEFAULT 'open',
    resolution VARCHAR(100),
    resolved_at TIMESTAMPTZ,
    resolved_by UUID,
    code_snippet TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

CREATE TABLE findings_2026_04 PARTITION OF findings
    FOR VALUES FROM ('2026-04-01'::TIMESTAMPTZ) TO ('2026-05-01'::TIMESTAMPTZ);

CREATE TABLE findings_2026_05 PARTITION OF findings
    FOR VALUES FROM ('2026-05-01'::TIMESTAMPTZ) TO ('2026-06-01'::TIMESTAMPTZ);

CREATE INDEX idx_findings_audit_run ON findings(audit_run_id);
CREATE INDEX idx_findings_project_severity ON findings(project_id, severity);
CREATE INDEX idx_findings_fingerprint ON findings(fingerprint);
CREATE INDEX idx_findings_status ON findings(status);
CREATE INDEX idx_findings_file_path_trgm ON findings USING gin(file_path gin_trgm_ops);

CREATE TRIGGER trigger_findings_updated_at
    BEFORE UPDATE ON findings
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();


-- LLM usage table (partitioned by created_at)
CREATE TABLE llm_usage (
    id UUID,
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    workflow_id VARCHAR(255),
    workflow_run_id VARCHAR(255),
    operation_mode VARCHAR(100),
    operation_detail VARCHAR(100),
    provider VARCHAR(50) NOT NULL,
    model VARCHAR(100) NOT NULL,
    prompt_tokens INT NOT NULL,
    completion_tokens INT NOT NULL,
    total_tokens INT GENERATED ALWAYS AS (prompt_tokens + completion_tokens) STORED,
    cost_usd DECIMAL(10,6),
    duration_ms INT,
    cached BOOLEAN DEFAULT FALSE,
    cache_key VARCHAR(64),
    request_id VARCHAR(255),
    temperature DECIMAL(3,2),
    max_tokens INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

CREATE TABLE llm_usage_2026_04 PARTITION OF llm_usage
    FOR VALUES FROM ('2026-04-01'::TIMESTAMPTZ) TO ('2026-05-01'::TIMESTAMPTZ);

CREATE TABLE llm_usage_2026_05 PARTITION OF llm_usage
    FOR VALUES FROM ('2026-05-01'::TIMESTAMPTZ) TO ('2026-06-01'::TIMESTAMPTZ);

CREATE INDEX idx_llm_usage_project_created ON llm_usage(project_id, created_at);
CREATE INDEX idx_llm_usage_provider_model ON llm_usage(provider, model);
CREATE INDEX idx_llm_usage_cached ON llm_usage(cached) WHERE cached = TRUE;

-- LLM cost hourly aggregation table
CREATE TABLE llm_cost_hourly (
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    hour_start TIMESTAMPTZ NOT NULL,
    provider VARCHAR(50) NOT NULL,
    model VARCHAR(100) NOT NULL,
    total_requests INT DEFAULT 0,
    total_prompt_tokens INT DEFAULT 0,
    total_completion_tokens INT DEFAULT 0,
    total_cost_usd DECIMAL(12,6) DEFAULT 0,
    cached_requests INT DEFAULT 0,
    PRIMARY KEY (project_id, hour_start, provider, model),
    CONSTRAINT valid_hour CHECK (EXTRACT(MINUTE FROM hour_start) = 0 AND EXTRACT(SECOND FROM hour_start) = 0)
);

CREATE INDEX idx_llm_cost_hourly_project ON llm_cost_hourly(project_id, hour_start DESC);

-- LLM cost daily aggregation table
CREATE TABLE llm_cost_daily (
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    day DATE NOT NULL,
    provider VARCHAR(50) NOT NULL,
    model VARCHAR(100) NOT NULL,
    total_requests INT DEFAULT 0,
    total_prompt_tokens INT DEFAULT 0,
    total_completion_tokens INT DEFAULT 0,
    total_cost_usd DECIMAL(12,6) DEFAULT 0,
    cached_requests INT DEFAULT 0,
    cache_hit_rate DECIMAL(5,2) GENERATED ALWAYS AS (
        CASE 
            WHEN total_requests > 0 THEN ROUND((cached_requests::NUMERIC / total_requests) * 100, 2)
            ELSE 0
        END
    ) STORED,
    cost_by_mode JSONB,
    PRIMARY KEY (project_id, day, provider, model)
);

CREATE INDEX idx_llm_cost_daily_project ON llm_cost_daily(project_id, day DESC);

-- Project cost limits table
CREATE TABLE project_cost_limits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    daily_limit_usd DECIMAL(10,2),
    monthly_limit_usd DECIMAL(12,2),
    alert_threshold_percent INT DEFAULT 80,
    alert_enabled BOOLEAN DEFAULT TRUE,
    action_on_exceed VARCHAR(50),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(project_id)
);

CREATE TRIGGER trigger_project_cost_limits_updated_at
    BEFORE UPDATE ON project_cost_limits
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Cost events tracking table
CREATE TABLE cost_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    event_type VARCHAR(100) NOT NULL,
    event_description TEXT,
    cost_usd DECIMAL(10,6),
    action_taken VARCHAR(255),
    triggered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_cost_events_project ON cost_events(project_id, created_at DESC);

-- API keys table
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    key_hash VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(255),
    scopes TEXT[] DEFAULT '{}',
    is_active BOOLEAN DEFAULT TRUE,
    last_used_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID
);

CREATE INDEX idx_api_keys_project_active ON api_keys(project_id, is_active);
CREATE INDEX idx_api_keys_key_hash ON api_keys(key_hash);
CREATE INDEX idx_api_keys_expires_at ON api_keys(expires_at) WHERE is_active = TRUE;

-- Code files table
CREATE TABLE code_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    file_hash VARCHAR(64),
    language VARCHAR(50),
    file_type VARCHAR(50),
    lines_of_code INT,
    complexity_score DECIMAL(8,2),
    directory_path ltree,
    dependency_count INT DEFAULT 0,
    dependent_count INT DEFAULT 0,
    last_analyzed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(project_id, file_path)
);

CREATE INDEX idx_code_files_project ON code_files(project_id);
CREATE INDEX idx_code_files_language ON code_files(project_id, language);
CREATE INDEX idx_code_files_path_gist ON code_files USING gist(directory_path);
CREATE INDEX idx_code_files_path_btree ON code_files USING btree(directory_path);
CREATE INDEX idx_code_files_trgm ON code_files USING gin(file_path gin_trgm_ops);

CREATE TRIGGER trigger_code_files_updated_at
    BEFORE UPDATE ON code_files
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();


-- File dependencies table
CREATE TABLE file_dependencies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_file_id UUID NOT NULL REFERENCES code_files(id) ON DELETE CASCADE,
    target_file_id UUID NOT NULL REFERENCES code_files(id) ON DELETE CASCADE,
    dependency_type VARCHAR(100),
    import_statement TEXT,
    is_external BOOLEAN DEFAULT FALSE,
    is_circular BOOLEAN DEFAULT FALSE,
    usage_count INT DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(source_file_id, target_file_id, dependency_type),
    CONSTRAINT different_files CHECK (source_file_id != target_file_id)
);

CREATE INDEX idx_file_deps_source ON file_dependencies(source_file_id);
CREATE INDEX idx_file_deps_target ON file_dependencies(target_file_id);
CREATE INDEX idx_file_deps_circular ON file_dependencies(is_circular) WHERE is_circular = TRUE;
CREATE INDEX idx_file_deps_external ON file_dependencies(is_external) WHERE is_external = TRUE;

CREATE TRIGGER trigger_file_dependencies_updated_at
    BEFORE UPDATE ON file_dependencies
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Finding relationships table
CREATE TABLE finding_relationships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    finding_id UUID NOT NULL,
    related_finding_id UUID NOT NULL,
    relationship_type VARCHAR(100) NOT NULL,
    confidence DECIMAL(5,2),
    detected_by VARCHAR(100),
    reason TEXT,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT different_findings CHECK (finding_id != related_finding_id)
);

CREATE INDEX idx_finding_relationships_finding ON finding_relationships(finding_id);
CREATE INDEX idx_finding_relationships_related ON finding_relationships(related_finding_id);
CREATE INDEX idx_finding_relationships_type ON finding_relationships(relationship_type);
CREATE INDEX idx_finding_relationships_confidence ON finding_relationships(confidence DESC);

-- Standards hierarchy table
CREATE TABLE standards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hierarchy_path ltree UNIQUE NOT NULL,
    level INT GENERATED ALWAYS AS (nlevel(hierarchy_path)) STORED,
    parent_id UUID REFERENCES standards(id) ON DELETE CASCADE,
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    company_id UUID,
    rules JSONB,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    version VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_standards_path_gist ON standards USING gist(hierarchy_path);
CREATE INDEX idx_standards_path_btree ON standards USING btree(hierarchy_path);
CREATE INDEX idx_standards_project ON standards(project_id) WHERE is_active = TRUE;
CREATE INDEX idx_standards_company ON standards(company_id) WHERE is_active = TRUE;
CREATE INDEX idx_standards_level ON standards(level);
CREATE INDEX idx_standards_active ON standards(is_active);

CREATE TRIGGER trigger_standards_updated_at
    BEFORE UPDATE ON standards
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- SCHEMA MIGRATION TRACKING
-- ============================================================================

CREATE TABLE schema_migrations (
    version INT PRIMARY KEY,
    migration_name VARCHAR(255) NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Record this migration
INSERT INTO schema_migrations (version, migration_name) VALUES (1, '001_initial_schema');
