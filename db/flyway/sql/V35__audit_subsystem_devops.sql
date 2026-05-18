-- V35: Extend spine_audit.audit_event.subsystem CHECK to add ``devops``.
--
-- Wave 3 (v3 rebuild, 2026-05, Squad A) adds the ``devops`` subsystem
-- identifier in shared/audit/audit_record.py::ALLOWED_SUBSYSTEMS to back
-- the Operate-subsystem 6th-corner role (#11 — devops role + 8 control
-- planes, distinct from the Spine-internal ``operator``). V33 already
-- extended the CHECK to the 8-value catalog; this migration extends it
-- to the v3 9-value catalog so write_via_psql rows emitted by
-- devops/planes/* with ``subsystem='devops'`` no longer fail the CHECK.
--
-- Catalog (must match shared/audit/audit_record.py::ALLOWED_SUBSYSTEMS):
--   plan, build, verify, orchestrator, shared,
--   hub, federation, integration, devops
--
-- Idempotency contract: this script may be applied repeatedly without
-- error. We DROP the constraint only if it exists, then ADD only if the
-- (final) constraint is not present. Both operations are wrapped in
-- DO ... END blocks that query information_schema.table_constraints.
-- Mirrors the style of V33.

BEGIN;

-- ─────────────────────────────────────────────────────────────────────
-- Step 1: drop whichever CHECK is in place (V15 5-value OR V33 8-value).
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
-- Step 2: add the v3 9-value CHECK if not already present.
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
                    'hub', 'federation', 'integration', 'devops'
                )
            );
    END IF;
END $$;

-- Keep the COMMENT in sync with the new catalog so \d+ output stays accurate.
COMMENT ON COLUMN spine_audit.audit_event.subsystem IS
    'plan | build | verify | orchestrator | shared | hub | federation | integration | devops.';

COMMIT;
