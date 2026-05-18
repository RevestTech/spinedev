-- V30: LLM provider + model catalog — Design Decisions #2, #20.
-- Runtime provider selection, cost tracking, capability discovery.

CREATE SCHEMA IF NOT EXISTS spine_provider;

COMMENT ON SCHEMA spine_provider IS
'LLM provider + model catalog: runtime selection, cost tracking, capability discovery.';

-- ─────────────────────────────────────────────────────────────────────
-- ENUM: provider_name — 7 providers per #2
-- ─────────────────────────────────────────────────────────────────────

DO $$ BEGIN
    CREATE TYPE spine_provider.provider_name AS ENUM (
        'anthropic','openai','bedrock','vertex','ollama','qwen','vllm'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE spine_provider.auth_type AS ENUM (
        'api_key','oauth2','aws_sigv4','azure_managed_identity','gcp_workload_identity','none'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

COMMENT ON TYPE spine_provider.provider_name IS '7 LLM providers per #2 LLM-agnostic.';
COMMENT ON TYPE spine_provider.auth_type     IS 'Provider authentication mechanism.';

-- ─────────────────────────────────────────────────────────────────────
-- llm_provider — registered provider endpoints
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_provider.llm_provider (
    id           uuid                         PRIMARY KEY DEFAULT gen_random_uuid(),
    name         spine_provider.provider_name NOT NULL,
    base_url     text                         NOT NULL,
    auth_type    spine_provider.auth_type     NOT NULL DEFAULT 'api_key',
    models_jsonb jsonb                        NOT NULL DEFAULT '[]',
    status       text                         NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled','deprecated')),
    created_at   timestamptz                  NOT NULL DEFAULT now(),
    updated_at   timestamptz,
    CONSTRAINT uq_llm_provider UNIQUE (name, base_url)
);

COMMENT ON TABLE  spine_provider.llm_provider IS 'Registered LLM provider endpoints. models_jsonb is denormalized quick reference; canonical pricing in llm_model.';
COMMENT ON COLUMN spine_provider.llm_provider.name         IS 'Provider identity.';
COMMENT ON COLUMN spine_provider.llm_provider.base_url     IS 'API base URL; varies for self-hosted or regional.';
COMMENT ON COLUMN spine_provider.llm_provider.auth_type    IS 'Auth mechanism.';
COMMENT ON COLUMN spine_provider.llm_provider.models_jsonb IS 'Quick-reference JSON array of model IDs.';
COMMENT ON COLUMN spine_provider.llm_provider.status       IS 'active | disabled | deprecated.';

CREATE TRIGGER trg_llm_provider_touch BEFORE UPDATE ON spine_provider.llm_provider
    FOR EACH ROW EXECUTE FUNCTION public._touch_updated_at();

CREATE INDEX idx_llm_provider_name   ON spine_provider.llm_provider (name);
CREATE INDEX idx_llm_provider_status ON spine_provider.llm_provider (status);

-- ─────────────────────────────────────────────────────────────────────
-- llm_model — per-model pricing + capability metadata
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_provider.llm_model (
    id                       uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_id              uuid          NOT NULL,
    model_id                 text          NOT NULL,
    input_price_per_million  numeric(12,6) CHECK (input_price_per_million  IS NULL OR input_price_per_million  >= 0),
    output_price_per_million numeric(12,6) CHECK (output_price_per_million IS NULL OR output_price_per_million >= 0),
    cache_read_price         numeric(12,6) CHECK (cache_read_price         IS NULL OR cache_read_price         >= 0),
    cache_write_price        numeric(12,6) CHECK (cache_write_price        IS NULL OR cache_write_price        >= 0),
    max_tokens               integer       CHECK (max_tokens               IS NULL OR max_tokens               > 0),
    created_at               timestamptz   NOT NULL DEFAULT now(),
    updated_at               timestamptz,
    CONSTRAINT fk_llm_model_provider FOREIGN KEY (provider_id) REFERENCES spine_provider.llm_provider (id) ON DELETE CASCADE,
    CONSTRAINT uq_llm_model UNIQUE (provider_id, model_id)
);

COMMENT ON TABLE  spine_provider.llm_model IS 'Per-model pricing + capability metadata. Prices USD per million tokens.';
COMMENT ON COLUMN spine_provider.llm_model.provider_id              IS 'Parent provider.';
COMMENT ON COLUMN spine_provider.llm_model.model_id                 IS 'Provider-native model identifier (e.g. claude-sonnet-4-6).';
COMMENT ON COLUMN spine_provider.llm_model.input_price_per_million  IS 'USD per 1M input tokens.';
COMMENT ON COLUMN spine_provider.llm_model.output_price_per_million IS 'USD per 1M output tokens.';
COMMENT ON COLUMN spine_provider.llm_model.cache_read_price         IS 'USD per 1M cache-read tokens.';
COMMENT ON COLUMN spine_provider.llm_model.cache_write_price        IS 'USD per 1M cache-write tokens.';
COMMENT ON COLUMN spine_provider.llm_model.max_tokens               IS 'Maximum context window in tokens.';

CREATE TRIGGER trg_llm_model_touch BEFORE UPDATE ON spine_provider.llm_model
    FOR EACH ROW EXECUTE FUNCTION public._touch_updated_at();

CREATE INDEX idx_llm_model_provider_id ON spine_provider.llm_model (provider_id);
CREATE INDEX idx_llm_model_model_id    ON spine_provider.llm_model (model_id);
