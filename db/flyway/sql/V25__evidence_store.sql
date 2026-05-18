-- V25: Evidence Store — Design Decision #24.
-- Compliance controls + evidence records + export log to Vanta/Drata/Secureframe.

CREATE SCHEMA IF NOT EXISTS spine_evidence;

COMMENT ON SCHEMA spine_evidence IS
'Evidence Store: compliance controls, evidence records, exporter audit log.';

-- ─────────────────────────────────────────────────────────────────────
-- control — one row per compliance control across frameworks
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_evidence.control (
    id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    framework   text        NOT NULL,
    control_id  text        NOT NULL,
    description text        NOT NULL,
    status      text        NOT NULL DEFAULT 'not_started'
                            CHECK (status IN ('not_started','in_progress','implemented','needs_review','failed')),
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz,
    CONSTRAINT uq_control_framework_id UNIQUE (framework, control_id)
);

COMMENT ON TABLE  spine_evidence.control IS 'Compliance controls from supported frameworks (SOC2/ISO27001/HIPAA/etc).';
COMMENT ON COLUMN spine_evidence.control.framework   IS 'SOC2 | ISO27001 | HIPAA | PCI_DSS | GDPR | NIST_CSF.';
COMMENT ON COLUMN spine_evidence.control.control_id  IS 'Native framework control id (e.g. CC6.1 for SOC2).';
COMMENT ON COLUMN spine_evidence.control.description IS 'Human-readable control requirement.';
COMMENT ON COLUMN spine_evidence.control.status      IS 'not_started | in_progress | implemented | needs_review | failed.';

CREATE TRIGGER trg_control_touch BEFORE UPDATE ON spine_evidence.control
    FOR EACH ROW EXECUTE FUNCTION public._touch_updated_at();

CREATE INDEX idx_control_framework ON spine_evidence.control (framework);
CREATE INDEX idx_control_status    ON spine_evidence.control (status);

-- ─────────────────────────────────────────────────────────────────────
-- evidence_record — individual evidence artifacts per control
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_evidence.evidence_record (
    id                         uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    control_id                 uuid        NOT NULL,
    source_audit_record_id     uuid,
    evidence_type              text        NOT NULL,
    collected_at               timestamptz NOT NULL DEFAULT now(),
    exported_at                timestamptz,
    exporter                   text CHECK (exporter IS NULL OR exporter IN ('vanta','drata','secureframe','tugboat','strikegraph','thoropass')),
    two_party_attestation_hash bytea,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz,
    CONSTRAINT fk_evidence_record_control FOREIGN KEY (control_id) REFERENCES spine_evidence.control (id) ON DELETE RESTRICT
);

COMMENT ON TABLE  spine_evidence.evidence_record IS 'Evidence artifacts linked to controls; supports two-party attestation hash.';
COMMENT ON COLUMN spine_evidence.evidence_record.control_id                 IS 'Compliance control this evidence satisfies.';
COMMENT ON COLUMN spine_evidence.evidence_record.source_audit_record_id     IS 'spine_audit.audit_record.id; FK enforced in Wave 1.';
COMMENT ON COLUMN spine_evidence.evidence_record.evidence_type              IS 'policy_doc | access_review | scan_result | test_run | config_snapshot.';
COMMENT ON COLUMN spine_evidence.evidence_record.collected_at               IS 'Capture timestamp.';
COMMENT ON COLUMN spine_evidence.evidence_record.exported_at                IS 'Last successful export; NULL = never.';
COMMENT ON COLUMN spine_evidence.evidence_record.exporter                   IS 'Target compliance vendor.';
COMMENT ON COLUMN spine_evidence.evidence_record.two_party_attestation_hash IS 'SHA-256 of (payload || attestor_A_sig || attestor_B_sig); NULL = single-party.';

CREATE TRIGGER trg_evidence_record_touch BEFORE UPDATE ON spine_evidence.evidence_record
    FOR EACH ROW EXECUTE FUNCTION public._touch_updated_at();

CREATE INDEX idx_evidence_record_control_id    ON spine_evidence.evidence_record (control_id);
CREATE INDEX idx_evidence_record_evidence_type ON spine_evidence.evidence_record (evidence_type);
CREATE INDEX idx_evidence_record_exporter      ON spine_evidence.evidence_record (exporter);
CREATE INDEX idx_evidence_record_collected_at  ON spine_evidence.evidence_record (collected_at);
CREATE INDEX idx_evidence_record_exported_at   ON spine_evidence.evidence_record (exported_at);

-- ─────────────────────────────────────────────────────────────────────
-- export_log — append-only audit of every exporter call
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_evidence.export_log (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    exporter        text        NOT NULL,
    target_url      text        NOT NULL,
    records_count   integer     NOT NULL DEFAULT 0 CHECK (records_count >= 0),
    exported_at     timestamptz NOT NULL DEFAULT now(),
    response_status integer,
    error           text,
    created_at      timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE  spine_evidence.export_log IS 'Append-only audit log of every evidence exporter HTTP call.';
COMMENT ON COLUMN spine_evidence.export_log.exporter        IS 'vanta | drata | secureframe | tugboat | strikegraph | thoropass.';
COMMENT ON COLUMN spine_evidence.export_log.target_url      IS 'Endpoint URL called.';
COMMENT ON COLUMN spine_evidence.export_log.records_count   IS 'Number of evidence_record rows in this batch.';
COMMENT ON COLUMN spine_evidence.export_log.exported_at     IS 'Export call timestamp.';
COMMENT ON COLUMN spine_evidence.export_log.response_status IS 'HTTP response status code.';
COMMENT ON COLUMN spine_evidence.export_log.error           IS 'Error message on failure; NULL on success.';

CREATE INDEX idx_export_log_exporter        ON spine_evidence.export_log (exporter);
CREATE INDEX idx_export_log_exported_at     ON spine_evidence.export_log (exported_at);
CREATE INDEX idx_export_log_response_status ON spine_evidence.export_log (response_status);
