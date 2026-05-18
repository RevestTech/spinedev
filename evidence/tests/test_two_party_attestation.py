"""Two-party attestation tests — V25 hash + verification flow."""
from __future__ import annotations

import hashlib
import unittest
from datetime import datetime, timezone

from evidence._types import EvidencePayload
from evidence.two_party_attestation import (
    attest, compute_attestation_hash, is_single_party, verify_attestation,
)


_TS = datetime(2026, 5, 17, 12, 0, 0, tzinfo=timezone.utc)


def _payload(**over):
    base = dict(
        framework="SOC2", control_id="CC6.1", evidence_type="access_review",
        source_audit_record_id="11111111-1111-1111-1111-111111111111",
        collected_at=_TS, body={"k": "v"},
    )
    base.update(over)
    return EvidencePayload(**base)


class AttestationHashTests(unittest.TestCase):
    def test_input_order_is_payload_then_a_then_b(self):
        """SHA-256 input order MUST be payload || sigA || sigB per V25."""
        p = _payload()
        sig_a = b"signature-A"
        sig_b = b"signature-B"
        actual = compute_attestation_hash(p, sig_a, sig_b)
        # Recompute manually following the documented order.
        expected = hashlib.sha256(p.canonical_json() + sig_a + sig_b).digest()
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), 32)  # SHA-256 -> 32 bytes

    def test_swapping_a_and_b_produces_different_hash(self):
        """A↔B swap MUST break corroboration (different hash output)."""
        p = _payload()
        h1 = compute_attestation_hash(p, b"A", b"B")
        h2 = compute_attestation_hash(p, b"B", b"A")
        self.assertNotEqual(h1, h2)

    def test_canonical_json_is_stable(self):
        """Same payload → same canonical bytes regardless of dict order."""
        p1 = _payload(body={"k": 1, "j": 2})
        p2 = _payload(body={"j": 2, "k": 1})
        self.assertEqual(p1.canonical_json(), p2.canonical_json())

    def test_payload_change_changes_hash(self):
        p1 = _payload(body={"k": 1})
        p2 = _payload(body={"k": 2})
        h1 = compute_attestation_hash(p1, b"A", b"B")
        h2 = compute_attestation_hash(p2, b"A", b"B")
        self.assertNotEqual(h1, h2)

    def test_non_bytes_signature_raises_typeerror(self):
        p = _payload()
        with self.assertRaises(TypeError):
            compute_attestation_hash(p, "not-bytes", b"B")  # type: ignore[arg-type]


class VerifyAttestationTests(unittest.TestCase):
    def test_verify_round_trip_true(self):
        p = _payload()
        sig_a, sig_b = b"signature-A", b"signature-B"
        h = compute_attestation_hash(p, sig_a, sig_b)
        self.assertTrue(verify_attestation(p, sig_a, sig_b, h))

    def test_verify_with_tampered_payload_false(self):
        p_orig = _payload(body={"k": 1})
        sig_a, sig_b = b"A", b"B"
        h = compute_attestation_hash(p_orig, sig_a, sig_b)
        p_tampered = _payload(body={"k": 999})
        self.assertFalse(verify_attestation(p_tampered, sig_a, sig_b, h))

    def test_verify_with_wrong_sig_false(self):
        p = _payload()
        h = compute_attestation_hash(p, b"A", b"B")
        self.assertFalse(verify_attestation(p, b"A-prime", b"B", h))

    def test_attest_helper_stamps_signatures(self):
        p = _payload()
        attest(p, attestor_a_signature=b"A", attestor_b_signature=b"B")
        self.assertEqual(p.attestor_a_signature, b"A")
        self.assertEqual(p.attestor_b_signature, b"B")

    def test_is_single_party_helper(self):
        self.assertTrue(is_single_party(None))
        self.assertTrue(is_single_party(b""))
        self.assertFalse(is_single_party(b"\x00" * 32))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
