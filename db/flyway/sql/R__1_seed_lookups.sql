-- R__1_seed_lookups: Seed lookup tables (tiers, levels, disciplines,
-- job families, roles).
--
-- REPEATABLE migration (R__ prefix): Flyway re-applies this whenever its
-- checksum changes, which is exactly what reference data wants. Changing a
-- seed value (e.g., renaming a tier) only requires editing this file; no
-- new versioned migration needed.
--
-- Ordering: Flyway runs R__ migrations in alphabetical order by
-- description. The numeric prefix ("1_") forces this file to run BEFORE
-- "R__2_model_pricing.sql", which depends on `tier` being populated for
-- its model.default_tier_id FK.
--
-- All inserts are idempotent via `ON CONFLICT DO NOTHING`. They run AFTER
-- the versioned schema migrations.

-- Tiers: keep human-readable names that match what the daemon writes to
-- costs.csv (lib/team-agent-daemon.sh parses tier hints into low|medium|high).
INSERT INTO tier (tier_id, name) VALUES
('low', 'LOW'),
('medium', 'MEDIUM'),
('high', 'HIGH')
ON CONFLICT (tier_id) DO NOTHING;

INSERT INTO level (level_id, name, rank) VALUES
('junior', 'junior', 1),
('mid', 'mid', 2),
('senior', 'senior', 3),
('staff', 'staff', 4),
('principal', 'principal', 5)
ON CONFLICT (level_id) DO NOTHING;

INSERT INTO discipline (discipline_id, name) VALUES
('backend', 'backend'),
('frontend', 'frontend'),
('fullstack', 'fullstack'),
('ml', 'ml'),
('devops', 'devops')
ON CONFLICT (discipline_id) DO NOTHING;

INSERT INTO job_family (family_id, name) VALUES
('product', 'product'),
('planner', 'planner'),
('architect', 'architect'),
('conductor', 'conductor'),
('researcher', 'researcher'),
('engineer', 'engineer'),
('ux', 'ux'),
('qa', 'qa'),
('operator', 'operator'),
('datawright', 'datawright'),
('seer', 'seer'),
('auditor', 'auditor'),
('memory', 'memory')
ON CONFLICT (family_id) DO NOTHING;

-- Default roles: one per job family.
INSERT INTO role (role_id, name, family_id, level_id, default_tier_id) VALUES
('product', 'product', 'product', 'senior', 'medium'),
('planner', 'planner', 'planner', 'senior', 'medium'),
('architect', 'architect', 'architect', 'staff', 'high'),
('conductor', 'conductor', 'conductor', 'senior', 'medium'),
('researcher', 'researcher', 'researcher', 'senior', 'medium'),
('ux', 'ux', 'ux', 'senior', 'medium'),
('qa', 'qa', 'qa', 'senior', 'medium'),
('operator', 'operator', 'operator', 'senior', 'medium'),
('datawright', 'datawright', 'datawright', 'senior', 'medium'),
('seer', 'seer', 'seer', 'senior', 'low'),
('auditor', 'auditor', 'auditor', 'staff', 'high'),
('memory', 'memory', 'memory', NULL, 'low')
ON CONFLICT (role_id) DO NOTHING;

-- Generic engineer (discipline TBD; used by v1 -> v2 migration).
INSERT INTO role (role_id, name, family_id, level_id, default_tier_id) VALUES
('engineer', 'engineer (discipline TBD)', 'engineer', 'senior', 'medium')
ON CONFLICT (role_id) DO NOTHING;

-- Engineer roles by discipline.
INSERT INTO role (
    role_id, name, family_id, level_id, discipline_id, default_tier_id
) VALUES
(
    'engineer-backend',
    'engineer (backend)',
    'engineer',
    'senior',
    'backend',
    'medium'
),
(
    'engineer-frontend',
    'engineer (frontend)',
    'engineer',
    'senior',
    'frontend',
    'medium'
),
(
    'engineer-fullstack',
    'engineer (fullstack)',
    'engineer',
    'senior',
    'fullstack',
    'medium'
),
('engineer-ml', 'engineer (ml)', 'engineer', 'senior', 'ml', 'high'),
(
    'engineer-devops',
    'engineer (devops)',
    'engineer',
    'senior',
    'devops',
    'medium'
)
ON CONFLICT (role_id) DO NOTHING;
