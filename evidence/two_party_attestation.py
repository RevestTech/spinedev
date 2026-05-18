"""Two-party attestation per V3 #24 + V25 schema.

V25 ``spine_evidence.evidence_record.two_party_attestation_hash`` is a
``bytea`` column documented as::

    SHA-256 of (payload || attestor_A_sig || attestor_B_sig);
    NULL = single-party.

This module owns:

  * Canonicalisation of the evidence payload (delegates to
    ``EvidencePayload.canonical_json`` — sorted-keys JSON, UTC ISO 8601
    timestamps).
  * Hash assembly with a STRICTLY FIXED input order:

        SHA-256( payload_canonical_json
                 || attestor_A_signature
                 || attestor_B_signature )

    Order matters because both attestors must agree on the binding —
    swapping A and B would produce a different hash and break
    corroboration. Spine ALWAYS treats:

      * attestor_A = Spine itself (the customer's Spine deployment;
        signature derived from the audit_chain content_hash).
      * attestor_B = the customer's GRC tool / auditor (Vanta or Drata
        countersignature returned at evidence ingestion).

  * Verification flow:
      1. Caller supplies the original payload + both signature blobs +
         the stored hash from V25.
      2. We regenerate the hash with the SAME canonicalisation +
         concatenation order.
      3. Byte-for-byte equality → verified. Any mismatch → False (the
         evidence has been tampered with OR an attestor swapped).

Signatures are opaque ``bytes`` here — Ed25519 signature bytes / PGP
detached-sig bodies / raw bytes of the audit chain content_hash all
work; the hashing step is signature-scheme-agnostic.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Optional

from evidence._types import EvidencePayload

logger = logging.getLogger(__name__)


def compute_attestation_hash(
    payload: EvidencePayload,
    attestor_a_signature: bytes,
    attestor_b_signature: bytes,
) -> bytes:
    """Return the 32-byte SHA-256 hash per V25 schema.

    Input order is FIXED — see module docstring. The hash is returned as
    raw bytes (suitable for V25 bytea column); call ``.hex()`` to log.
    """
    if not isinstance(attestor_a_signature, (bytes, bytearray)):
        raise TypeError("attestor_a_signature must be bytes")
    if not isinstance(attestor_b_signature, (bytes, bytearray)):
        raise TypeError("attestor_b_signature must be bytes")
    h = hashlib.sha256()
    h.update(payload.canonical_json())
    h.update(bytes(attestor_a_signature))
    h.update(bytes(attestor_b_signature))
    digest = h.digest()
    logger.debug("compute_attestation_hash: control=%s/%s digest=%s",
                 payload.framework, payload.control_id, digest.hex())
    return digest


def attest(
    payload: EvidencePayload,
    *,
    attestor_a_signature: bytes,
    attestor_b_signature: bytes,
) -> EvidencePayload:
    """Stamp both signatures onto the payload (returns the same object).

    Convenience helper for the two-party flow: typically the caller has
    just computed signature A locally and received signature B back from
    the GRC vendor's countersignature endpoint.
    """
    payload.attestor_a_signature = bytes(attestor_a_signature)
    payload.attestor_b_signature = bytes(attestor_b_signature)
    return payload


def verify_attestation(
    payload: EvidencePayload,
    attestor_a_signature: bytes,
    attestor_b_signature: bytes,
    expected_hash: bytes,
) -> bool:
    """True iff regenerated hash matches the V25-stored bytes exactly.

    Wraps ``compute_attestation_hash`` and does a constant-time byte
    compare (``hmac.compare_digest``) to avoid timing oracles for the
    customer auditor's corroboration loop.
    """
    import hmac
    actual = compute_attestation_hash(payload, attestor_a_signature, attestor_b_signature)
    return hmac.compare_digest(actual, expected_hash)


def is_single_party(stored_hash: Optional[bytes]) -> bool:
    """V25 convention: NULL hash = single-party evidence."""
    return stored_hash is None or len(stored_hash) == 0


__all__ = [
    "compute_attestation_hash",
    "attest",
    "verify_attestation",
    "is_single_party",
]
