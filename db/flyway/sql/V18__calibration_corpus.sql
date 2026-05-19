-- V18: Confidence calibration corpus + fitted models (INIT-3 / EPIC-3.6).
--
-- Implements STORY-3.6.1 (move TRON calibration to shared), STORY-3.6.2
-- (labeled outcome corpus), STORY-3.6.3 (Platt when N>=500 else banded)
-- and STORY-3.6.4 (apply to architect/decomposer/qa/auditor outputs) from
-- docs/BACKLOG.md. Lifts TRON's L6 pattern
-- (verify/tron/services/calibration_engine.py) into a Spine-wide service.
-- Granularity: (role, output_type). Active model = valid_to IS NULL.

BEGIN;

CREATE SCHEMA IF NOT EXISTS spine_calibration;
COMMENT ON SCHEMA spine_calibration IS
'Labeled corpus + fitted models for LLM-only confidence calibration across Plan/Build/Verify roles.';

-- prediction -- every LLM output we want to calibrate (raw, untouched).
CREATE TABLE spine_calibration.prediction (
    id BIGSERIAL PRIMARY KEY,
    predicted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    role TEXT NOT NULL,
    output_type TEXT NOT NULL,
    project_id BIGINT,
    subject_id TEXT,
    predicted_value NUMERIC(6, 4) NOT NULL,
    raw_features JSONB NOT NULL DEFAULT '{}'::JSONB,
    audit_event_id BIGINT REFERENCES spine_audit.audit_event (event_id),
    CONSTRAINT prediction_value_chk CHECK (predicted_value >= 0 AND predicted_value <= 1)
);
COMMENT ON TABLE spine_calibration.prediction IS 'Raw LLM confidence/score per (role, output_type); X axis of calibration.';
COMMENT ON COLUMN spine_calibration.prediction.output_type IS 'risk_score | story_estimate | severity | finding_confidence | ...';
COMMENT ON COLUMN spine_calibration.prediction.raw_features IS 'JSON: model, tokens, role context, anything useful as a calibration feature.';
CREATE INDEX idx_prediction_role_type_ts ON spine_calibration.prediction (role, output_type, predicted_at DESC);
CREATE INDEX idx_prediction_project ON spine_calibration.prediction (project_id) WHERE project_id IS NOT NULL;
CREATE INDEX idx_prediction_audit ON spine_calibration.prediction (audit_event_id) WHERE audit_event_id IS NOT NULL;

-- outcome -- observed ground truth (when eventually known).
CREATE TABLE spine_calibration.outcome (
    id BIGSERIAL PRIMARY KEY,
    prediction_id BIGINT NOT NULL REFERENCES spine_calibration.prediction (id) ON DELETE CASCADE,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    observed_value NUMERIC(6, 4) NOT NULL,
    outcome_source TEXT NOT NULL,
    notes TEXT,
    CONSTRAINT outcome_value_chk CHECK (observed_value >= 0 AND observed_value <= 1),
    CONSTRAINT outcome_source_chk CHECK (
        outcome_source IN
        ('user_approval', 'verify_pass', 'prod_incident', 'time_elapsed', 'manual_review')
    )
);
COMMENT ON TABLE spine_calibration.outcome IS 'Observed ground truth in [0,1] paired to a prediction; Y axis of calibration.';
COMMENT ON COLUMN spine_calibration.outcome.outcome_source IS 'user_approval | verify_pass | prod_incident | time_elapsed | manual_review.';
CREATE INDEX idx_outcome_prediction ON spine_calibration.outcome (prediction_id);
CREATE INDEX idx_outcome_observed ON spine_calibration.outcome (observed_at DESC);

-- calibration_model -- fitted mappings per (role, output_type). Active model
-- = valid_to IS NULL. Refit writes a new row and sets valid_to=NOW() on the
-- prior active row inside one transaction.
CREATE TABLE spine_calibration.calibration_model (
    id BIGSERIAL PRIMARY KEY,
    role TEXT NOT NULL,
    output_type TEXT NOT NULL,
    model_type TEXT NOT NULL,
    fit_params JSONB NOT NULL,
    n_samples INTEGER NOT NULL,
    fitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_to TIMESTAMPTZ,
    CONSTRAINT cm_model_type_chk CHECK (model_type IN ('platt', 'banded', 'identity')),
    CONSTRAINT cm_n_samples_chk CHECK (n_samples >= 0),
    CONSTRAINT cm_validity_chk CHECK (valid_to IS NULL OR valid_to >= valid_from),
    CONSTRAINT cm_unique_fit UNIQUE (role, output_type, fitted_at)
);
COMMENT ON TABLE spine_calibration.calibration_model IS 'Fitted calibration mappings per (role, output_type). Active row = valid_to IS NULL.';
COMMENT ON COLUMN spine_calibration.calibration_model.model_type IS 'platt: sigmoid(A*x+B); banded: per-decile TP-rate dict; identity: pass-through.';
COMMENT ON COLUMN spine_calibration.calibration_model.fit_params IS 'platt={"A":..,"B":..}; banded={"bands":{"0.0-0.1":0.05,...}}; identity={}.';
CREATE INDEX idx_cm_role_type_history ON spine_calibration.calibration_model (role, output_type, fitted_at DESC);
CREATE UNIQUE INDEX uq_cm_one_active_per_pair
ON spine_calibration.calibration_model (role, output_type) WHERE valid_to IS NULL;

-- v_calibration_status -- per (role, output_type): sample count, active model, band.
CREATE OR REPLACE VIEW spine_calibration.v_calibration_status AS
WITH counts AS (
    SELECT
        p.role,
        p.output_type,
        COUNT(*) FILTER (WHERE o.id IS NOT NULL)::INT AS labeled_samples,
        COUNT(*)::INT AS predictions
    FROM spine_calibration.prediction AS p
    LEFT JOIN spine_calibration.outcome AS o ON o.prediction_id = p.id
    GROUP BY p.role, p.output_type
)

SELECT
    c.role,
    c.output_type,
    c.labeled_samples,
    c.predictions,
    m.model_type AS active_model_type,
    m.n_samples AS active_n_samples,
    m.fitted_at AS active_fitted_at,
    CASE
        WHEN c.labeled_samples >= 500 THEN 'platt-eligible'
        WHEN c.labeled_samples >= 50 THEN 'banded'
        ELSE 'untrusted'
    END AS calibration_band
FROM counts AS c
LEFT JOIN spine_calibration.calibration_model AS m
    ON m.role = c.role AND m.output_type = c.output_type AND m.valid_to IS NULL
ORDER BY c.role, c.output_type;
COMMENT ON VIEW spine_calibration.v_calibration_status IS
'Per (role, output_type): labeled sample count, active model type/age, calibration band the corpus has unlocked.';

-- v_pending_outcomes -- predictions awaiting an outcome row.
CREATE OR REPLACE VIEW spine_calibration.v_pending_outcomes AS
SELECT
    p.id,
    p.role,
    p.output_type,
    p.project_id,
    p.subject_id,
    p.predicted_value,
    p.predicted_at,
    EXTRACT(EPOCH FROM (NOW() - p.predicted_at))::INT AS age_seconds
FROM spine_calibration.prediction AS p
LEFT JOIN spine_calibration.outcome AS o ON o.prediction_id = p.id
WHERE o.id IS NULL
ORDER BY p.predicted_at ASC;
COMMENT ON VIEW spine_calibration.v_pending_outcomes IS
'Predictions awaiting an outcome row -- the queue for manual labelers and automated outcome collectors.';

COMMIT;
