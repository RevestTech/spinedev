-- R__2_model_pricing: Seed provider + model pricing tables.
--
-- REPEATABLE migration (R__ prefix): Flyway re-applies this whenever its
-- checksum changes. That's the right fit for reference pricing — updating a
-- per-1k-token cost is just an edit + redeploy, no V<N>__ bump needed.
--
-- Ordering: Flyway runs R__ migrations in alphabetical order by
-- description. The numeric prefix ("2_") forces this file to run AFTER
-- "R__1_seed_lookups.sql" — model.default_tier_id FK-references the
-- `tier` table which R__1 populates.
--
-- All inserts are idempotent (ON CONFLICT DO NOTHING).
--
-- ─────────────────────────────────────────────────────────────────────
-- Pricing notes
-- ─────────────────────────────────────────────────────────────────────
-- The `model` table stores prices per 1,000 tokens (NUMERIC(12,6)) — this
-- matches the column definition in V1__init_core_schema.sql. Vendors typically
-- advertise pricing per 1M tokens; convert by dividing by 1000.
--
-- Anthropic pricing source: Anthropic's published pricing page as of the date
-- this seed was added (May 2026). Costs are USD per 1M tokens converted to
-- USD per 1k tokens:
--   - Opus 4.x   : $15.00/M in, $75.00/M out   -> 0.015 / 0.075
--   - Sonnet 4.x : $3.00/M  in, $15.00/M out   -> 0.003 / 0.015
--   - Haiku 4.5  : $1.00/M  in, $5.00/M  out   -> 0.001 / 0.005
-- The 4-5 alias rows for sonnet/opus carry the same prices as 4-6 because the
-- daemon may surface either model id depending on which version Claude Code
-- happens to route to. Real prices will be reconciled when those tier names
-- actually settle.
--
-- OpenAI pricing (APPROXIMATE — public estimates as of May 2026; verify
-- against your account's billing page before relying on these for $$ decisions):
--   - gpt-5      : $5.00/M in, $20.00/M out    -> 0.005 / 0.020
--   - gpt-4o     : $2.50/M in, $10.00/M out    -> 0.0025 / 0.01
--   - gpt-4o-mini: $0.15/M in, $0.60/M out     -> 0.00015 / 0.0006
--
-- Local Ollama models: cost is genuinely zero on inference (compute is sunk
-- cost). Both in/out columns are 0.
--
-- Models not listed here still ingest: the watcher's resolve_model_id() falls
-- back to NULL on a lookup miss and logs a warning. Add a row here when a new
-- model starts showing up in logs.

-- ─────────────────────────────────────────────────────────────────────
-- Providers
-- ─────────────────────────────────────────────────────────────────────

INSERT INTO provider (provider_id, name) VALUES
('anthropic', 'Anthropic'),
('openai', 'OpenAI'),
('local-ollama', 'local-ollama')
ON CONFLICT (provider_id) DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────
-- Anthropic models
-- ─────────────────────────────────────────────────────────────────────

INSERT INTO model (
    model_id, provider_id, name,
    cost_in_usd_per_1k_tokens, cost_out_usd_per_1k_tokens,
    default_tier_id
) VALUES
(
    'claude-opus-4-6', 'anthropic', 'Claude Opus 4.6',
    0.015000, 0.075000, 'high'
),
(
    'claude-opus-4-5', 'anthropic', 'Claude Opus 4.5 (alias)',
    0.015000, 0.075000, 'high'
),
(
    'claude-sonnet-4-6', 'anthropic', 'Claude Sonnet 4.6',
    0.003000, 0.015000, 'medium'
),
(
    'claude-sonnet-4-5', 'anthropic', 'Claude Sonnet 4.5 (alias)',
    0.003000, 0.015000, 'medium'
),
(
    'claude-haiku-4-5-20251001', 'anthropic', 'Claude Haiku 4.5 (2025-10-01)',
    0.001000, 0.005000, 'low'
)
ON CONFLICT (model_id) DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────
-- OpenAI models  (APPROXIMATE pricing — see header comment)
-- ─────────────────────────────────────────────────────────────────────

INSERT INTO model (
    model_id, provider_id, name,
    cost_in_usd_per_1k_tokens, cost_out_usd_per_1k_tokens,
    default_tier_id
) VALUES
('gpt-5', 'openai', 'GPT-5', 0.005000, 0.020000, 'high'),
('gpt-4o', 'openai', 'GPT-4o', 0.002500, 0.010000, 'medium'),
('gpt-4o-mini', 'openai', 'GPT-4o mini', 0.000150, 0.000600, 'low')
ON CONFLICT (model_id) DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────
-- Local (Ollama) models — zero marginal cost
-- ─────────────────────────────────────────────────────────────────────

INSERT INTO model (
    model_id, provider_id, name,
    cost_in_usd_per_1k_tokens, cost_out_usd_per_1k_tokens,
    default_tier_id
) VALUES
('qwen-7b', 'local-ollama', 'Qwen 7B (local)', 0.000000, 0.000000, 'low'),
('qwen-72b', 'local-ollama', 'Qwen 72B (local)', 0.000000, 0.000000, 'medium'),
(
    'llama-3-70b',
    'local-ollama',
    'Llama 3 70B (local)',
    0.000000,
    0.000000,
    'medium'
)
ON CONFLICT (model_id) DO NOTHING;
