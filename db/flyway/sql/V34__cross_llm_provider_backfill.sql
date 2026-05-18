-- V34: Backfill legacy cross-LLM provider labels in audit metadata.
--
-- Per V3 design decision #2 (LLM-agnostic — provider migration) the
-- ``Provider`` Literal in shared/validation/cross_llm.py dropped the legacy
-- labels ``google`` and ``local`` and replaced them with the v3 7-tuple
-- (anthropic / openai / bedrock / vertex / ollama / qwen / vllm). The
-- module docstring records the mapping rule:
--
--   * ``google`` → ``vertex``  (Gemini-on-Vertex AI is the v3 home)
--   * ``local``  → ``ollama``  (default per #2; vllm is opt-in)
--
-- Persisted rows produced by pre-v3 cross_llm calls landed with the old
-- labels in ``spine_audit.audit_event.metadata``. The Pydantic Literal now
-- refuses to round-trip those rows, so we rewrite them in place.
--
-- Storage shape produced by shared/validation/cross_llm.py::_write_audit:
--   metadata.providers : [
--      { "provider": "<name>", "model": "...", "verdict": "...", ... },
--      ...
--   ]
-- A nested ``provider`` key can also appear at the top of metadata for
-- legacy rows or for action-specific records (e.g., llm_call). We handle
-- both shapes by canonicalising the JSON text once per row.
--
-- Idempotency contract: the rewrites are pure string replacements that
-- produce v3-valid output. Re-running the migration is a no-op because
-- the WHERE clause filters rows whose canonical text still contains a
-- legacy label.
--
-- Append-only enforcement (V15) installs UPDATE/DELETE triggers on
-- ``spine_audit.audit_event``. Forensic backfill requires temporarily
-- detaching those triggers; we do so inside the transaction so a
-- ROLLBACK (or any failure) leaves the append-only guarantee intact.

BEGIN;

-- ─────────────────────────────────────────────────────────────────────
-- Step 1: temporarily disable the append-only triggers for this txn.
-- A ROLLBACK reverts BOTH the DDL (DISABLE TRIGGER) and the UPDATE.
-- ─────────────────────────────────────────────────────────────────────
ALTER TABLE spine_audit.audit_event DISABLE TRIGGER trg_audit_event_no_update;

-- ─────────────────────────────────────────────────────────────────────
-- Step 2: rewrite ``"provider": "google"`` -> ``"provider": "vertex"``.
-- Use jsonb -> text -> jsonb so nested array entries (metadata.providers)
-- and top-level scalars (metadata.provider) are both covered in one pass.
-- ─────────────────────────────────────────────────────────────────────
UPDATE spine_audit.audit_event
SET    metadata = REPLACE(metadata::text, '"provider": "google"', '"provider": "vertex"')::jsonb
WHERE  metadata::text LIKE '%"provider": "google"%';

-- Same rewrite for the compact JSON form (no space after the colon) emitted
-- by some serialisers (``json.dumps(..., separators=(",", ":"))``).
UPDATE spine_audit.audit_event
SET    metadata = REPLACE(metadata::text, '"provider":"google"', '"provider":"vertex"')::jsonb
WHERE  metadata::text LIKE '%"provider":"google"%';

-- ─────────────────────────────────────────────────────────────────────
-- Step 3: rewrite ``"provider": "local"`` -> ``"provider": "ollama"``.
-- Default per cross_llm.py docstring (#2); operators who actually ran
-- vLLM in their pre-v3 deployment must update those rows by hand — there
-- is no signal in ``metadata`` to disambiguate at backfill time.
-- ─────────────────────────────────────────────────────────────────────
UPDATE spine_audit.audit_event
SET    metadata = REPLACE(metadata::text, '"provider": "local"', '"provider": "ollama"')::jsonb
WHERE  metadata::text LIKE '%"provider": "local"%';

UPDATE spine_audit.audit_event
SET    metadata = REPLACE(metadata::text, '"provider":"local"', '"provider":"ollama"')::jsonb
WHERE  metadata::text LIKE '%"provider":"local"%';

-- ─────────────────────────────────────────────────────────────────────
-- Step 4: re-enable the append-only triggers.
-- ─────────────────────────────────────────────────────────────────────
ALTER TABLE spine_audit.audit_event ENABLE TRIGGER trg_audit_event_no_update;

COMMIT;
