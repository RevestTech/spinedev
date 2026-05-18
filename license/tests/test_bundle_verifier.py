"""Tests for ``license.bundle_verifier``."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from license import bundle_verifier
from license.bundle_verifier import (
    ActiveBundle,
    BundleVerificationError,
    canonicalise,
    fingerprint,
    verify_signature,
)
from shared.schemas.license import (
    FeatureFlag,
    LicenseBundlePayload,
    SignedLicenseBundle,
)


def _payload(**over):
    base = dict(
        customer="acme",
        tier="team",
        bundle_id="bundle-1",
        issued_at=datetime.now(timezone.utc),
        expires_at=None,
        feature_flags=[FeatureFlag(flag_name="federation", enabled=True)],
    )
    base.update(over)
    return LicenseBundlePayload(**base)


def test_canonicalise_is_deterministic() -> None:
    p = _payload()
    a = canonicalise(p)
    b = canonicalise(p)
    assert a == b
    # Sorted-keys property: a key reorder would still produce the same bytes.
    assert b'"tier":"team"' in a


def test_fingerprint_is_hex_sha256() -> None:
    fp = fingerprint(b"\x00" * 32)
    assert len(fp) == 64
    assert all(c in "0123456789abcdef" for c in fp)


def test_verify_signature_happy_path(vendor_keypair, make_signed) -> None:
    env = make_signed(key=vendor_keypair.private,
                      fingerprint=vendor_keypair.fingerprint)
    payload = verify_signature(env, vendor_public_key_bytes=vendor_keypair.public_bytes)
    assert payload.tier == "team"
    assert payload.customer == "test-customer"


def test_verify_rejects_fingerprint_mismatch(vendor_keypair, make_signed) -> None:
    env = make_signed(key=vendor_keypair.private,
                      fingerprint="f" * 64)  # wrong fp in envelope
    with pytest.raises(BundleVerificationError) as ei:
        verify_signature(env, vendor_public_key_bytes=vendor_keypair.public_bytes)
    assert ei.value.code == "fingerprint_mismatch"


def test_verify_rejects_untrusted_vendor_key(vendor_keypair, make_signed,
                                              monkeypatch) -> None:
    # Trust anchor diverges from the actual key — the bake-time guard.
    monkeypatch.setattr(bundle_verifier, "TRUSTED_VENDOR_FINGERPRINT", "0" * 64,
                        raising=False)
    env = make_signed(key=vendor_keypair.private,
                      fingerprint=vendor_keypair.fingerprint)
    with pytest.raises(BundleVerificationError) as ei:
        verify_signature(env, vendor_public_key_bytes=vendor_keypair.public_bytes)
    assert ei.value.code == "untrusted_vendor_key"


def test_verify_rejects_invalid_signature(vendor_keypair, make_signed) -> None:
    env = make_signed(key=vendor_keypair.private,
                      fingerprint=vendor_keypair.fingerprint)
    # Flip a bit in the signature.
    sig = bytearray(base64.b64decode(env.signature_b64))
    sig[0] ^= 0x01
    bad = SignedLicenseBundle(
        payload_canonical_b64=env.payload_canonical_b64,
        signature_b64=base64.b64encode(bytes(sig)).decode("ascii"),
        signing_key_fingerprint=env.signing_key_fingerprint,
    )
    with pytest.raises(BundleVerificationError) as ei:
        verify_signature(bad, vendor_public_key_bytes=vendor_keypair.public_bytes)
    assert ei.value.code == "invalid_signature"


def test_verify_rejects_wrong_payload_version(vendor_keypair, make_signed) -> None:
    """Bundle whose canonical bytes don't parse as v1 should be rejected."""
    # Build a payload that's valid JSON but missing required fields.
    import json
    bogus = json.dumps({"payload_version": "license-bundle-v999"}).encode()
    sig = vendor_keypair.private.sign(bogus)
    env = SignedLicenseBundle(
        payload_canonical_b64=base64.b64encode(bogus).decode("ascii"),
        signature_b64=base64.b64encode(sig).decode("ascii"),
        signing_key_fingerprint=vendor_keypair.fingerprint,
    )
    with pytest.raises(BundleVerificationError) as ei:
        verify_signature(env, vendor_public_key_bytes=vendor_keypair.public_bytes)
    assert ei.value.code == "payload_parse_failed"


def test_active_bundle_is_expired() -> None:
    p = _payload(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    bundle = ActiveBundle(payload=p)
    assert bundle.is_currently_valid() is False


def test_active_bundle_signature_invalidation_blocks_valid() -> None:
    p = _payload()
    bundle = ActiveBundle(payload=p, signature_ok=False)
    assert bundle.is_currently_valid() is False
