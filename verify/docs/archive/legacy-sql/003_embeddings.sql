-- Migration 003: Code Embeddings
-- Vector embeddings for semantic code search
-- PostgreSQL 15+

-- ============================================================================
-- CODE EMBEDDINGS TABLE
-- ============================================================================

CREATE TABLE code_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_id UUID NOT NULL REFERENCES code_files(id) ON DELETE CASCADE,
    embedding vector(3072),
    text_chunk TEXT NOT NULL,
    chunk_index INT DEFAULT 0,
    chunk_type VARCHAR(50),  -- function, class, module, comment
    token_count INT,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT valid_chunk_type CHECK (
        chunk_type IS NULL OR chunk_type IN ('function', 'class', 'module', 'comment', 'other')
    )
);

CREATE INDEX idx_code_embeddings_file ON code_embeddings(file_id);
CREATE INDEX idx_code_embeddings_vector ON code_embeddings 
    USING ivfflat (embedding vector_cosine_ops) 
    WITH (lists = 100);
CREATE INDEX idx_code_embeddings_type ON code_embeddings(chunk_type, file_id);
CREATE INDEX idx_code_embeddings_created ON code_embeddings(created_at DESC);

-- ============================================================================
-- ENHANCE FINDINGS TABLE WITH FILE REFERENCE
-- ============================================================================

ALTER TABLE findings ADD COLUMN IF NOT EXISTS file_id UUID 
    REFERENCES code_files(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_findings_file_id ON findings(file_id);

-- ============================================================================
-- SCHEMA MIGRATION TRACKING
-- ============================================================================

INSERT INTO schema_migrations (version, migration_name) 
VALUES (3, '003_embeddings') 
ON CONFLICT (version) DO NOTHING;
