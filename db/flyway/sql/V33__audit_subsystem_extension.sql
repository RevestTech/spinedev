-- V33: Extend spine_audit.audit_event.subsystem CHECK to v3 8-value catalog.
--
-- Wave 1 (v3 rebuild, 2026-05) added three subsystem identifiers in
-- shared/audit/audit_record.py::ALLOWED_SUBSYSTEMS — ``hub``, ``federation``,
-- ``integration`` — in addition to the original five (``plan``, ``build``,
-- ``verify``, ``orchestrator``, ``shared``). The Pydantic validator is the
-- in-process gate; this migration is the durability gate at the DB layer so
-- ``write_via_psql`` rows with new subsystems no longer fail the CHECK.
--
-- Catalog (must match shared/audit/audit_record.py::ALLOWED_SUBSYSTEMS):
--   plan, build, verify, orchestrator, shared, hub, federation, integration
--
-- Idempotency contract: this script may be applied repeatedly without
-- error. We DROP the constraint only if it exists, then ADD only if the
-- (final) constraint is not present. Both operations are wrapped in
-- DO ... END blocks that query information_schema.table_constraints.

BEGIN;

-- ─────────────────────────────────────────────────────────────────────
-- Step 1: drop the V15-shipped CHECK if it is still in place.
-- ─────────────────────────────────────────────────────────────────────
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM   information_schema.table_constraints
        WHERE  table_schema   = 'spine_audit'
          AND  table_name     = 'audit_event'
          AND  constraint_name = 'audit_event_subsystem_chk'
          AND  constraint_type = 'CHECK'
    ) THEN
        ALTER TABLE spine_audit.audit_event
            DROP CONSTRAINT audit_event_subsystem_chk;
    END IF;
END $$;

-- ─────────────────────────────────────────────────────────────────────
-- Step 2: add the v3 CHECK if it is not already present.
-- ─────────────────────────────────────────────────────────────────────
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM   information_schema.table_constraints
        WHERE  table_schema   = 'spine_audit'
          AND  table_name     = 'audit_event'
          AND  constraint_name = 'audit_event_subsystem_chk'
          AND  constraint_type = 'CHECK'
    ) THEN
        ALTER TABLE spine_audit.audit_event
            ADD CONSTRAINT audit_event_subsystem_chk CHECK (
                subsystem IN (
                    'plan', 'build', 'verify', 'orchestrator', 'shared',
                    'hub', 'federation', 'integration'
                )
            );
    END IF;
END $$;

-- Keep the COMMENT in sync with the new catalog so \d+ output stays accurate.
COMMENT ON COLUMN spine_audit.audit_event.subsystem IS
    'plan | build | verify | orchestrator | shared | hub | federation | integration.';

COMMIT;
