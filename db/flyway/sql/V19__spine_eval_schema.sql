-- V19: spine_eval — role-prompt eval harness storage (EPIC-3.4).
--
-- Implements STORY-3.4.2 (eval runner), STORY-3.4.3 (regression mode), and
-- STORY-3.4.4 (A/B mode) per docs/BACKLOG.md. Schema sketched in
-- shared/eval/runner_design.md §8. Consumed by shared/eval/{runner,scorer,
-- aggregator,reporter,cli}.py. Drift-check semantics live in loader.py.
--
-- Storage shape: three tables — dataset (registry), eval_run (one row per
-- runner invocation), case_result (one row per case per run). A/B outcomes
-- get their own table so the (paired baseline, paired candidate) shape is
-- preserved without coercing eval_run rows. Per-check breakdowns live in
-- case_result.check_results JSONB so we don't ossify the rubric shape into
-- columns the dashboard would have to re-pivot anyway.

BEGIN;

CREATE SCHEMA IF NOT EXISTS spine_eval;
COMMENT ON SCHEMA spine_eval IS
  'Role-prompt eval datasets, runs, and per-case scores (EPIC-3.4).';

CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid()

-- ─────────────────────────────────────────────────────────────────────
-- dataset — registry of known eval datasets (one row per dataset_id).
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE spine_eval.dataset (
    id           BIGSERIAL    PRIMARY KEY,
    dataset_id   TEXT         NOT NULL UNIQUE,
    role         TEXT         NOT NULL,
    version      INTEGER      NOT NULL,
    path         TEXT         NOT NULL,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    case_count   INTEGER      NOT NULL,
    CONSTRAINT dataset_case_count_chk CHECK (case_count >= 0),
    CONSTRAINT dataset_version_chk    CHECK (version >= 1)
);
COMMENT ON TABLE  spine_eval.dataset            IS 'Registered eval datasets — one row per dataset_id; loader upserts on first run.';
COMMENT ON COLUMN spine_eval.dataset.dataset_id IS 'Stable slug from dataset YAML (e.g. "engineer-core-v1"). Unique across the registry.';
COMMENT ON COLUMN spine_eval.dataset.role       IS 'Spine role the dataset targets (engineer, architect, planner, ...).';
COMMENT ON COLUMN spine_eval.dataset.version    IS 'Monotonically incremented when the dataset YAML is materially edited.';
COMMENT ON COLUMN spine_eval.dataset.path       IS 'Repo-relative path to the dataset YAML at registration time.';
COMMENT ON COLUMN spine_eval.dataset.case_count IS 'Number of cases in the YAML at registration time; for sanity checks against eval_run pass/fail totals.';

-- ─────────────────────────────────────────────────────────────────────
-- eval_run — one row per `spine eval run|regression|ab|smoke` invocation.
-- baseline_* columns are only populated for regression / ab modes.
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE spine_eval.eval_run (
    id                     BIGSERIAL      PRIMARY KEY,
    run_uuid               UUID           NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    dataset_id             TEXT           NOT NULL REFERENCES spine_eval.dataset(dataset_id),
    candidate_prompt_path  TEXT           NOT NULL,
    candidate_prompt_sha   TEXT           NOT NULL,
    candidate_model        TEXT           NOT NULL,
    baseline_prompt_sha    TEXT,
    baseline_model         TEXT,
    started_at             TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    completed_at           TIMESTAMPTZ,
    mode                   TEXT           NOT NULL,
    total_cost_usd         NUMERIC(10, 4),
    aggregate_score        NUMERIC(6, 4),
    pass_count             INTEGER        NOT NULL DEFAULT 0,
    fail_count             INTEGER        NOT NULL DEFAULT 0,
    skip_count             INTEGER        NOT NULL DEFAULT 0,
    actor                  TEXT           NOT NULL,
    CONSTRAINT eval_run_mode_chk    CHECK (mode IN ('full', 'regression', 'ab', 'smoke')),
    CONSTRAINT eval_run_score_chk   CHECK (aggregate_score IS NULL OR (aggregate_score >= 0 AND aggregate_score <= 1)),
    CONSTRAINT eval_run_cost_chk    CHECK (total_cost_usd IS NULL OR total_cost_usd >= 0),
    CONSTRAINT eval_run_counts_chk  CHECK (pass_count >= 0 AND fail_count >= 0 AND skip_count >= 0),
    CONSTRAINT eval_run_shalen_chk  CHECK (char_length(candidate_prompt_sha) = 64)
);
COMMENT ON TABLE  spine_eval.eval_run                      IS 'One row per runner invocation (full / regression / ab / smoke). UPDATEd in place on completion.';
COMMENT ON COLUMN spine_eval.eval_run.candidate_prompt_sha IS 'SHA-256 of the candidate role-prompt file at run time; drives regression diffing.';
COMMENT ON COLUMN spine_eval.eval_run.baseline_prompt_sha  IS 'SHA-256 of the baseline prompt the candidate was compared against; NULL for mode=full.';
COMMENT ON COLUMN spine_eval.eval_run.mode                 IS 'full = score against rubric only; regression = diff vs baseline run; ab = paired baseline/candidate; smoke = single random case.';
COMMENT ON COLUMN spine_eval.eval_run.aggregate_score      IS 'Severity-weighted mean of case scores in [0,1]; see aggregator.aggregate_run().';
COMMENT ON COLUMN spine_eval.eval_run.actor                IS 'User handle or system principal that launched the eval (mirrors spine_audit.audit_event.actor).';

-- ─────────────────────────────────────────────────────────────────────
-- case_result — one row per case per run; per-check breakdown in JSONB.
-- ON DELETE CASCADE: dropping an eval_run drops its case_results too.
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE spine_eval.case_result (
    id               BIGSERIAL      PRIMARY KEY,
    eval_run_id      BIGINT         NOT NULL REFERENCES spine_eval.eval_run(id) ON DELETE CASCADE,
    case_id          TEXT           NOT NULL,
    score            NUMERIC(6, 4)  NOT NULL,
    pass_fail        TEXT           NOT NULL,
    check_results    JSONB          NOT NULL DEFAULT '[]'::jsonb,
    output_artifact  TEXT,
    cost_usd         NUMERIC(10, 4),
    duration_ms      INTEGER,
    error_message    TEXT,
    CONSTRAINT case_result_pass_chk     CHECK (pass_fail IN ('pass', 'fail', 'skip', 'error')),
    CONSTRAINT case_result_score_chk    CHECK (score >= 0 AND score <= 1),
    CONSTRAINT case_result_cost_chk     CHECK (cost_usd IS NULL OR cost_usd >= 0),
    CONSTRAINT case_result_duration_chk CHECK (duration_ms IS NULL OR duration_ms >= 0)
);
COMMENT ON TABLE  spine_eval.case_result               IS 'Per-case score for one eval_run; check_results JSONB carries the per-check breakdown.';
COMMENT ON COLUMN spine_eval.case_result.case_id       IS 'case_id from the dataset YAML; (eval_run_id, case_id) is logically unique but not constrained (re-runs allowed on retry).';
COMMENT ON COLUMN spine_eval.case_result.score         IS 'Final case score in [0,1] after the rubric scoring_method has been applied.';
COMMENT ON COLUMN spine_eval.case_result.check_results IS 'Array of {check_id, check_type, score, passed, weight, must_pass, detail} objects; mirrors scorer.CheckResult.';
COMMENT ON COLUMN spine_eval.case_result.output_artifact IS 'Path or URL to the captured candidate output (e.g. eval-runs/<run_uuid>/<case_id>/stdout.txt).';

-- ─────────────────────────────────────────────────────────────────────
-- Indexes — primary access patterns are "latest run for dataset_id" and
-- "all case_results for a run." A/B mode reuses these.
-- ─────────────────────────────────────────────────────────────────────
CREATE INDEX idx_eval_run_dataset_started   ON spine_eval.eval_run (dataset_id, started_at DESC);
CREATE INDEX idx_eval_run_mode_started      ON spine_eval.eval_run (mode, started_at DESC);
CREATE INDEX idx_case_result_run_case       ON spine_eval.case_result (eval_run_id, case_id);
CREATE INDEX idx_case_result_check_gin      ON spine_eval.case_result USING GIN (check_results jsonb_path_ops);

COMMIT;
