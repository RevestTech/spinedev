-- V36: Persistent decision cards (#5 active push) + persistence wiring for
-- federation graph reuse — Wave 3.5 FIX3.
--
-- Replaces the in-process ``_DecisionStore`` (shared/api/routes/decisions.py)
-- + the in-process ``_GRAPH`` dict (shared/api/routes/federation.py) with
-- Postgres-backed storage. Federation persistence reuses V23 tables
-- (spine_federation.hub + consent_record); only decisions need new schema.
--
-- Per #5 the AI Scrum Master / PM / Release Manager actively pushes
-- decision cards to business users; per #12 each card preserves a
-- ``citations`` payload so the verify-class cite-or-refuse contract is
-- recoverable from the card itself. Per #19 the kind is open-text so
-- new work-item types do not require a migration.
--
-- DELETE policy: rows are NEVER deleted (status transitions to
-- ``superseded`` instead). Append-only character matches the audit log
-- model in V15, so cross-table joins on (project_id, ts) stay cheap.

BEGIN;

CREATE SCHEMA IF NOT EXISTS spine_lifecycle;

CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid()

-- ─────────────────────────────────────────────────────────────────────
-- decision_card — one row per active-push card surfaced to a user.
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS spine_lifecycle.decision_card (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id BIGINT REFERENCES spine_lifecycle.project (id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    severity TEXT NOT NULL DEFAULT 'info',
    status TEXT NOT NULL DEFAULT 'pending',
    pushed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at TIMESTAMPTZ,
    decided_by TEXT,
    expires_at TIMESTAMPTZ,
    citations JSONB NOT NULL DEFAULT '[]'::JSONB,
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    CONSTRAINT decision_card_status_chk CHECK (
        status IN ('pending', 'acked', 'rejected', 'superseded', 'expired')
    ),
    CONSTRAINT decision_card_severity_chk CHECK (
        severity IN ('info', 'warning', 'critical')
    )
);

COMMENT ON TABLE spine_lifecycle.decision_card IS 'Active-push decision cards (#5); persistent across Hub restart + federation.';
COMMENT ON COLUMN spine_lifecycle.decision_card.id IS 'External-facing stable decision_id (UUID).';
COMMENT ON COLUMN spine_lifecycle.decision_card.project_id IS 'spine_lifecycle.project.id when scoped; NULL for Hub-global cards (briefings, license events).';
COMMENT ON COLUMN spine_lifecycle.decision_card.kind IS 'Decision class: approval | incident | release | briefing | budget | policy_change | ... (open text per #19).';
COMMENT ON COLUMN spine_lifecycle.decision_card.title IS 'Short summary the SPA renders as the card heading.';
COMMENT ON COLUMN spine_lifecycle.decision_card.body IS 'Card body — markdown allowed; up to 8 KiB enforced at API layer.';
COMMENT ON COLUMN spine_lifecycle.decision_card.severity IS 'info | warning | critical — drives notification routing per #6.';
COMMENT ON COLUMN spine_lifecycle.decision_card.status IS 'pending | acked | rejected | superseded | expired.';
COMMENT ON COLUMN spine_lifecycle.decision_card.pushed_at IS 'When the Hub first pushed the card to the user (#5 active push).';
COMMENT ON COLUMN spine_lifecycle.decision_card.decided_at IS 'When the user resolved the card; NULL while pending.';
COMMENT ON COLUMN spine_lifecycle.decision_card.decided_by IS 'Actor handle that resolved the card (matches audit_event.actor).';
COMMENT ON COLUMN spine_lifecycle.decision_card.expires_at IS 'Optional soft expiry; expired cards become status=expired by sweeper.';
COMMENT ON COLUMN spine_lifecycle.decision_card.citations IS 'Cite-or-Refuse evidence per #12: list of {kg_node_id|file_line|audit_event_id}.';
COMMENT ON COLUMN spine_lifecycle.decision_card.metadata IS 'Free-form JSON (correlation_id, source_role, surface, ...).';

CREATE INDEX IF NOT EXISTS idx_decision_card_status_pushed ON spine_lifecycle.decision_card (status, pushed_at DESC);
CREATE INDEX IF NOT EXISTS idx_decision_card_project_pushed ON spine_lifecycle.decision_card (project_id, pushed_at DESC);
CREATE INDEX IF NOT EXISTS idx_decision_card_kind ON spine_lifecycle.decision_card (kind);

-- Reuse the shared updated-at trigger if present (V1 ships ``set_updated_at``).
-- decision_card does NOT track updated_at on every row because status
-- transitions go through decided_at / status fields explicitly.

COMMIT;
