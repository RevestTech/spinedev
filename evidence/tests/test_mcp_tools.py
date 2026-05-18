"""MCP tool tests for evidence — registry tagging + smoke calls (all mocked)."""
from __future__ import annotations

import binascii
import unittest
from datetime import datetime, timezone
from unittest import mock

from evidence._types import EvidencePayload, ExportResult
from evidence.two_party_attestation import compute_attestation_hash
from shared.mcp.tools import TOOL_REGISTRY, discover_tools
from shared.mcp.tools.evidence import (
    EvidenceAttestationVerifyInput, EvidenceCollectInput,
    EvidenceExportInput, evidence_attestation_verify, evidence_collect,
    evidence_export,
)


_TS = datetime(2026, 5, 17, 12, 0, 0, tzinfo=timezone.utc)


def _payload():
    return EvidencePayload(
        framework="SOC2", control_id="CC6.1", evidence_type="access_review",
        source_audit_record_id="11111111-1111-1111-1111-111111111111",
        collected_at=_TS, body={"k": "v"},
    )


class RegistryTaggingTests(unittest.TestCase):
    """V3 #12 — collect + export must be requires_citation=True."""

    @classmethod
    def setUpClass(cls):
        discover_tools("shared.mcp.tools")

    def test_evidence_collect_requires_citation(self):
        spec = TOOL_REGISTRY.get("evidence_collect")
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertTrue(spec.requires_citation,
            "evidence_collect must be requires_citation=True (V3 #12)")

    def test_evidence_export_requires_citation(self):
        spec = TOOL_REGISTRY.get("evidence_export")
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertTrue(spec.requires_citation,
            "evidence_export must be requires_citation=True (V3 #12)")

    def test_evidence_status_no_citation_required(self):
        spec = TOOL_REGISTRY.get("evidence_status")
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertFalse(spec.requires_citation)

    def test_evidence_attestation_verify_no_citation_required(self):
        spec = TOOL_REGISTRY.get("evidence_attestation_verify")
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertFalse(spec.requires_citation)

    def test_all_four_tools_registered(self):
        for n in ("evidence_collect", "evidence_export",
                  "evidence_status", "evidence_attestation_verify"):
            self.assertIn(n, TOOL_REGISTRY, f"missing {n}")


class EvidenceCollectTests(unittest.TestCase):
    def test_emits_citations_per_payload(self):
        with mock.patch("shared.mcp.tools.evidence._dispatch_collector",
                        return_value=[_payload(), _payload()]):
            resp = evidence_collect(EvidenceCollectInput(
                collector="audit_chain", framework="SOC2", control_id="CC6.1",
                project_id="proj-1",
            ))
        self.assertEqual(resp.status, "ok")
        self.assertEqual(resp.data["payload_count"], 2)
        # One fallback citation + one per unique source_audit_record_id.
        # Both payloads share the same source_audit_record_id so the
        # dedupe keeps it to 1 + 1 = 2 citations total.
        self.assertGreaterEqual(len(resp.citation), 1)
        self.assertTrue(any(c.type == "audit_hash" for c in resp.citation))

    def test_collector_failure_returns_error_envelope(self):
        with mock.patch("shared.mcp.tools.evidence._dispatch_collector",
                        side_effect=RuntimeError("boom")):
            resp = evidence_collect(EvidenceCollectInput(
                collector="audit_chain", framework="SOC2", control_id="CC6.1",
                project_id="proj-1",
            ))
        self.assertEqual(resp.status, "error")
        assert resp.error is not None
        self.assertEqual(resp.error.code, "collector_failed")


class EvidenceExportTests(unittest.TestCase):
    def test_empty_payloads_short_circuits_with_citation(self):
        with mock.patch("shared.mcp.tools.evidence._dispatch_collector",
                        return_value=[]):
            resp = evidence_export(EvidenceExportInput(
                exporter="vanta", framework="SOC2", control_id="CC6.1",
                project_id="proj-1",
            ))
        self.assertEqual(resp.status, "ok")
        self.assertEqual(resp.data["records_count"], 0)
        # Per #12 we still emit a citation (the audit_hash fallback).
        self.assertGreaterEqual(len(resp.citation), 1)

    def test_successful_export_returns_ok_with_citations(self):
        fake_result = ExportResult(
            exporter="vanta", target_url="https://api.vanta.com/v1/evidence",
            records_count=1, response_status=202, success=True, error=None,
        )
        with mock.patch("shared.mcp.tools.evidence._dispatch_collector",
                        return_value=[_payload()]), \
             mock.patch("shared.mcp.tools.evidence._build_exporter") as build:
            build.return_value.send.return_value = fake_result
            resp = evidence_export(EvidenceExportInput(
                exporter="vanta", framework="SOC2", control_id="CC6.1",
                project_id="proj-1",
            ))
        self.assertEqual(resp.status, "ok")
        self.assertTrue(resp.data["success"])
        self.assertGreaterEqual(len(resp.citation), 1)

    def test_v1_1_stub_returns_explicit_error_code(self):
        with mock.patch("shared.mcp.tools.evidence._dispatch_collector",
                        return_value=[_payload()]), \
             mock.patch("shared.mcp.tools.evidence._build_exporter") as build:
            build.return_value.send.side_effect = NotImplementedError("v1.1+")
            resp = evidence_export(EvidenceExportInput(
                exporter="tugboat", framework="SOC2", control_id="CC6.1",
                project_id="proj-1",
            ))
        self.assertEqual(resp.status, "error")
        assert resp.error is not None
        self.assertEqual(resp.error.code, "exporter_v1_1_stub")
        self.assertFalse(resp.error.retryable)

    def test_http_failure_records_error_with_retryable(self):
        fake_result = ExportResult(
            exporter="vanta", target_url="https://api.vanta.com/v1/evidence",
            records_count=1, response_status=500, success=False,
            error="500 Internal Server Error",
        )
        with mock.patch("shared.mcp.tools.evidence._dispatch_collector",
                        return_value=[_payload()]), \
             mock.patch("shared.mcp.tools.evidence._build_exporter") as build:
            build.return_value.send.return_value = fake_result
            resp = evidence_export(EvidenceExportInput(
                exporter="vanta", framework="SOC2", control_id="CC6.1",
                project_id="proj-1",
            ))
        self.assertEqual(resp.status, "error")
        assert resp.error is not None
        self.assertTrue(resp.error.retryable)


class EvidenceAttestationVerifyTests(unittest.TestCase):
    def test_verifies_legitimate_hash(self):
        p = _payload()
        sig_a, sig_b = b"A" * 16, b"B" * 16
        h = compute_attestation_hash(p, sig_a, sig_b)
        resp = evidence_attestation_verify(EvidenceAttestationVerifyInput(
            framework=p.framework, control_id=p.control_id,
            evidence_type=p.evidence_type,
            source_audit_record_id=p.source_audit_record_id,
            collected_at=p.collected_at, body=p.body,
            attestor_a_signature_hex=binascii.hexlify(sig_a).decode(),
            attestor_b_signature_hex=binascii.hexlify(sig_b).decode(),
            expected_hash_hex=binascii.hexlify(h).decode(),
            project_id="proj-1",
        ))
        self.assertEqual(resp.status, "ok")
        self.assertTrue(resp.data["verified"])

    def test_rejects_tampered_payload(self):
        p = _payload()
        sig_a, sig_b = b"A" * 16, b"B" * 16
        h = compute_attestation_hash(p, sig_a, sig_b)
        resp = evidence_attestation_verify(EvidenceAttestationVerifyInput(
            framework=p.framework, control_id=p.control_id,
            evidence_type=p.evidence_type,
            source_audit_record_id=p.source_audit_record_id,
            collected_at=p.collected_at,
            body={"k": "TAMPERED"},  # ← changed
            attestor_a_signature_hex=binascii.hexlify(sig_a).decode(),
            attestor_b_signature_hex=binascii.hexlify(sig_b).decode(),
            expected_hash_hex=binascii.hexlify(h).decode(),
            project_id="proj-1",
        ))
        self.assertEqual(resp.status, "ok")
        self.assertFalse(resp.data["verified"])

    def test_invalid_hex_returns_error(self):
        resp = evidence_attestation_verify(EvidenceAttestationVerifyInput(
            framework="SOC2", control_id="CC6.1",
            evidence_type="access_review", collected_at=_TS, body={},
            attestor_a_signature_hex="zz" * 8,
            attestor_b_signature_hex="aa" * 8,
            expected_hash_hex="ab" * 32,
            project_id="proj-1",
        ))
        self.assertEqual(resp.status, "error")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
