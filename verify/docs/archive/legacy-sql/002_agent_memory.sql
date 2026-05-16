-- Migration 002: Agent Memory System
-- Tables for agent memory and prompt management
-- PostgreSQL 15+

-- ============================================================================
-- AGENT MEMORY TABLE
-- ============================================================================

CREATE TABLE agent_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id VARCHAR(100) NOT NULL,
    memory_type VARCHAR(50) NOT NULL,  -- episodic, semantic, procedural, working, meta
    key TEXT NOT NULL,
    value JSONB NOT NULL,
    text TEXT NOT NULL,
    embedding vector(3072),
    metadata JSONB,
    importance DECIMAL(3,2) DEFAULT 0.5,
    access_count INT DEFAULT 0,
    last_accessed_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT valid_memory_type CHECK (
        memory_type IN ('episodic', 'semantic', 'procedural', 'working', 'meta')
    ),
    CONSTRAINT valid_importance CHECK (importance >= 0 AND importance <= 1.0)
);

CREATE INDEX idx_agent_memory_agent ON agent_memory(agent_id, memory_type);
CREATE INDEX idx_agent_memory_key ON agent_memory(agent_id, key);
CREATE INDEX idx_agent_memory_embedding ON agent_memory 
    USING ivfflat (embedding vector_cosine_ops) 
    WITH (lists = 100);
CREATE INDEX idx_agent_memory_importance ON agent_memory(agent_id, importance DESC);
CREATE INDEX idx_agent_memory_recent ON agent_memory(agent_id, created_at DESC);
CREATE INDEX idx_agent_memory_expires ON agent_memory(expires_at) 
    WHERE expires_at IS NOT NULL;

-- ============================================================================
-- PROMPT TEMPLATES TABLE
-- ============================================================================

CREATE TABLE prompt_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id VARCHAR(100) NOT NULL,
    version VARCHAR(20) NOT NULL,
    template TEXT NOT NULL,
    variables JSONB NOT NULL,
    model VARCHAR(50) NOT NULL,
    temperature DECIMAL(3,2) DEFAULT 0.7,
    max_tokens INT,
    is_active BOOLEAN DEFAULT TRUE,
    usage_count INT DEFAULT 0,
    avg_quality_score DECIMAL(5,2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(template_id, version),
    CONSTRAINT valid_temperature CHECK (temperature >= 0 AND temperature <= 2.0)
);

CREATE INDEX idx_prompt_templates_active ON prompt_templates(template_id) 
    WHERE is_active = TRUE;
CREATE INDEX idx_prompt_templates_model ON prompt_templates(model, template_id);
CREATE INDEX idx_prompt_templates_usage ON prompt_templates(usage_count DESC);
CREATE INDEX idx_prompt_templates_quality ON prompt_templates(avg_quality_score DESC) 
    WHERE avg_quality_score IS NOT NULL;

-- Create trigger for updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_prompt_templates_updated_at
    BEFORE UPDATE ON prompt_templates
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- SCHEMA MIGRATION TRACKING
-- ============================================================================

INSERT INTO schema_migrations (version, migration_name) 
VALUES (2, '002_agent_memory') 
ON CONFLICT (version) DO NOTHING;
