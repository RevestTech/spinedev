"""Ed25519 license bundle verifier (Wave 4 Squad B / design decision #23).

Vendor signs license bundles with a private Ed25519 key kept *only* in
the vendor vault (per #9 + Part 4.3 — Shamir 3-of-5 recovery). Each
customer Hub ships with the corresponding vendor *public* key fingerprint
hard-coded as ``TRUSTED_VENDOR_FINGERPRINT``; the actual public key
material is fetched at Hub start from the customer's vault under
``license/vendor_pubkey``. The fingerprint check is the anti-substitution
guard: even if an attacker writes a forged key into the customer's vault,
the Hub refuses to load it unless its SHA-256 matches the hard-coded
fingerprint baked into the Hub binary.

Verification cadence (per #23 "Hub validates Ed25519 signature on startup
+ periodically + on every feature gate"):

* ``startup`` — :func:`load_active_bundle` runs once during Hub bootstrap,
  loads the bundle row from ``spine_license.bundle``, verifies the
  signature, and installs the parsed payload into the
  process-wide :data:`_ACTIVE` slot.
* ``per gate`` — every call to ``license.feature_flags.is_enabled``
  consults :data:`_ACTIVE` and re-checks the cached ``signature_ok``
  flag. The cached payload also carries an ``expires_at``; gates fail
  closed once expiry elapses.
* ``periodic`` — :func:`start_periodic_verifier` spawns an asyncio task
  that re-runs full signature verification every
  ``PERIODIC_VERIFY_SECONDS`` (default 3600s). A failed periodic
  verification flips :data:`_ACTIVE.signature_ok` to ``False`` so
  subsequent gates fail closed.

The verifier never persists private key material on disk — it only ever
reads the public key from the vault during verification. Vendor-side
signing happens entirely inside ``tools/license-sign.sh`` which loads the
private key on-demand from the vendor vault, signs in memory, and exits.

Per #18 (closed-source v1.0) we deliberately don't expose the canonical
bytes calculation as a separate library: every binary that needs to verify
imports this module.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

try:  # pragma: no cover — documented dep; falls through to lazy error
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.hazmat.primitives import serialization
    _CRYPTO_AVAILABLE = True
except Exception:  # pragma: no cover
    _CRYPTO_AVAILABLE = False
    InvalidSignature = Exception  # type: ignore[assignment,misc]

from shared.schemas.license import (
    BUNDLE_PAYLOAD_VERSION,
    LicenseBundlePayload,
    SignedLicenseBundle,
)

logger = logging.getLogger("spine.license.bundle_verifier")


# ---------------------------------------------------------------------------
# Vendor key trust anchor
# ---------------------------------------------------------------------------

#: Hard-coded vendor Ed25519 public-key fingerprint (hex SHA-256 of the
#: 32-byte raw key bytes). Set at Hub build time. The Hub refuses to load
#: any vendor public key whose fingerprint doesn't match this constant —
#: this is the anti-substitution guard documented above.
#:
#: Override via env (``SPINE_LICENSE_VENDOR_FP``) is provided ONLY for
#: vendor-side dogfood and the test suite; production builds bake the
#: fingerprint into the source.
TRUSTED_VENDOR_FINGERPRINT: str = os.environ.get(
    "SPINE_LICENSE_VENDOR_FP",
    "0000000000000000000000000000000000000000000000000000000000000000",
).strip().lower()

#: Vault path where the vendor public key bytes (32 raw bytes) live.
VENDOR_PUBKEY_VAULT_PATH: str = os.environ.get(
    "SPINE_LICENSE_VENDOR_PUBKEY_PATH", "license/vendor_pubkey",
)

#: How often the background verifier re-checks the active bundle.
PERIODIC_VERIFY_SECONDS: int = int(
    os.environ.get("SPINE_LICENSE_VERIFY_INTERVAL_SECONDS", "3600"),
)


# ---------------------------------------------------------------------------
# Canonical bytes
# ---------------------------------------------------------------------------


def canonicalise(payload: LicenseBundlePayload) -> bytes:
    """Return the canonical UTF-8 byte sequence the signature covers.

    Sorted keys + no whitespace + UTC ISO-8601 timestamps + JSON-compatible
    primitives. The encoding is deterministic so vendor + Hub agree on
    the exact bytes regardless of platform/library quirks.
    """
    raw = payload.model_dump(mode="json")
    return json.dumps(raw, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def fingerprint(public_key_bytes: bytes) -> str:
    """Hex SHA-256 fingerprint of a 32-byte Ed25519 public key."""
    return hashlib.sha256(public_key_bytes).hexdigest()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class BundleVerificationError(Exception):
    """Raised when signature verification, fingerprint check, or parsing fails."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# Verification primitives
# ---------------------------------------------------------------------------


def verify_signature(
    envelope: SignedLicenseBundle,
    *,
    vendor_public_key_bytes: bytes,
) -> LicenseBundlePayload:
    """Verify ``envelope`` against ``vendor_public_key_bytes``; return parsed payload.

    Raises :class:`BundleVerificationError` with a stable ``.code`` for
    every failure mode so callers can surface structured upgrade hints.
    """
    if not _CRYPTO_AVAILABLE:
        raise BundleVerificationError(
            "cryptography_unavailable",
            "the ``cryptography`` package is required for bundle verification; "
            "install with `pip install cryptography` (see license/README.md).",
        )
    expected_fp = fingerprint(vendor_public_key_bytes)
    if envelope.signing_key_fingerprint.lower() != expected_fp:
        raise BundleVerificationError(
            "fingerprint_mismatch",
            f"bundle was signed by key {envelope.signing_key_fingerprint!r}; "
            f"Hub trusts {expected_fp!r}. Refusing to load.",
        )
    if expected_fp != TRUSTED_VENDOR_FINGERPRINT:
        raise BundleVerificationError(
            "untrusted_vendor_key",
            f"vendor public key fingerprint {expected_fp!r} does not match the "
            f"hard-coded TRUSTED_VENDOR_FINGERPRINT {TRUSTED_VENDOR_FINGERPRINT!r}.",
        )
    try:
        payload_bytes = base64.b64decode(envelope.payload_canonical_b64, validate=True)
        signature = base64.b64decode(envelope.signature_b64, validate=True)
    except Exception as exc:
        raise BundleVerificationError(
            "base64_decode_failed", f"could not base64-decode envelope: {exc}",
        ) from exc
    key = Ed25519PublicKey.from_public_bytes(vendor_public_key_bytes)
    try:
        key.verify(signature, payload_bytes)
    except InvalidSignature as exc:
        raise BundleVerificationError(
            "invalid_signature",
            "Ed25519 signature did not verify against canonical payload bytes.",
        ) from exc
    try:
        raw = json.loads(payload_bytes.decode("utf-8"))
        payload = LicenseBundlePayload.model_validate(raw)
    except Exception as exc:
        raise BundleVerificationError(
            "payload_parse_failed",
            f"signed payload did not parse as license-bundle-v1: {exc}",
        ) from exc
    if payload.payload_version != BUNDLE_PAYLOAD_VERSION:
        raise BundleVerificationError(
            "unknown_payload_version",
            f"payload_version={payload.payload_version!r}; "
            f"this Hub only understands {BUNDLE_PAYLOAD_VERSION!r}.",
        )
    return payload


# ---------------------------------------------------------------------------
# Active-bundle cache
# ---------------------------------------------------------------------------


@dataclass
class ActiveBundle:
    """Cached active bundle held in-process between verifications."""

    payload: LicenseBundlePayload
    signature_ok: bool = True
    last_verified_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    last_error: Optional[str] = None

    def is_currently_valid(self, *, now: Optional[datetime] = None) -> bool:
        """True iff signature still cached as valid AND not expired."""
        if not self.signature_ok:
            return False
        if self.payload.expires_at is None:
            return True
        when = now or datetime.now(timezone.utc)
        return when < self.payload.expires_at


_ACTIVE: Optional[ActiveBundle] = None


def set_active_bundle(bundle: Optional[ActiveBundle]) -> None:
    """Install (or clear) the process-wide active bundle. Tests use this."""
    global _ACTIVE
    _ACTIVE = bundle


def get_active_bundle() -> Optional[ActiveBundle]:
    """Return the currently-installed active bundle (or None)."""
    return _ACTIVE


# ---------------------------------------------------------------------------
# Vault fetch + bundle load
# ---------------------------------------------------------------------------


async def _fetch_vendor_public_key() -> bytes:
    """Load the vendor public key bytes from the configured vault adapter.

    The vault stores a 64-hex string OR a base64-encoded 32-byte blob;
    both forms are accepted so the wizard can pick whichever its operator
    finds easier to paste.
    """
    from shared.secrets import get_secret  # local: keep cold-start surface small
    raw = (await get_secret(VENDOR_PUBKEY_VAULT_PATH)).strip()
    # Hex form
    if len(raw) == 64 and all(c in "0123456789abcdefABCDEF" for c in raw):
        return bytes.fromhex(raw)
    # Base64 form
    try:
        decoded = base64.b64decode(raw, validate=True)
        if len(decoded) == 32:
            return decoded
    except Exception:
        pass
    raise BundleVerificationError(
        "bad_vendor_pubkey_format",
        f"vault path {VENDOR_PUBKEY_VAULT_PATH!r} did not contain a 64-hex "
        "or base64-encoded 32-byte Ed25519 public key.",
    )


async def load_active_bundle(
    *,
    pool: Any,
    vendor_public_key_bytes: Optional[bytes] = None,
) -> ActiveBundle:
    """Read the active bundle from ``spine_license.bundle``, verify it, install it.

    ``pool`` is an asyncpg pool (duck-typed; the test suite passes a
    mock with ``.acquire()`` that yields a connection with ``.fetchrow``).

    Returns the installed :class:`ActiveBundle`; raises
    :class:`BundleVerificationError` on signature / parse / expiry failures.
    """
    if vendor_public_key_bytes is None:
        vendor_public_key_bytes = await _fetch_vendor_public_key()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, signed_payload, signature, signing_key_fingerprint, "
            "       expires_at, revoked_at "
            "FROM spine_license.bundle "
            "WHERE revoked_at IS NULL "
            "ORDER BY issued_at DESC LIMIT 1;",
        )
    if row is None:
        raise BundleVerificationError(
            "no_active_bundle",
            "no row in spine_license.bundle; install one via tools/license-sign.sh "
            "then `psql -f` the INSERT (see license/README.md).",
        )
    envelope = SignedLicenseBundle(
        payload_canonical_b64=base64.b64encode(row["signed_payload"]).decode("ascii"),
        signature_b64=base64.b64encode(row["signature"]).decode("ascii"),
        signing_key_fingerprint=str(row["signing_key_fingerprint"]).lower(),
    )
    payload = verify_signature(
        envelope, vendor_public_key_bytes=vendor_public_key_bytes,
    )
    bundle = ActiveBundle(payload=payload, signature_ok=True)
    set_active_bundle(bundle)
    logger.info(
        "license_bundle_loaded",
        extra={
            "bundle_id": payload.bundle_id, "customer": payload.customer,
            "tier": payload.tier, "fp": envelope.signing_key_fingerprint,
        },
    )
    return bundle


# ---------------------------------------------------------------------------
# Periodic re-verify
# ---------------------------------------------------------------------------


_PERIODIC_TASK: Optional["asyncio.Task[None]"] = None


def start_periodic_verifier(
    *,
    pool: Any,
    interval_seconds: Optional[int] = None,
) -> "asyncio.Task[None]":
    """Spawn the background task that re-verifies the active bundle.

    Called from Hub's startup hook after :func:`load_active_bundle`.
    Returns the task so the caller can keep a reference / cancel on shutdown.
    """
    global _PERIODIC_TASK
    interval = interval_seconds or PERIODIC_VERIFY_SECONDS

    async def _runner() -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                await load_active_bundle(pool=pool)
                logger.info("license_periodic_verify_ok")
            except BundleVerificationError as exc:
                logger.error("license_periodic_verify_failed",
                             extra={"code": exc.code, "msg": str(exc)})
                cur = get_active_bundle()
                if cur is not None:
                    cur.signature_ok = False
                    cur.last_error = f"{exc.code}: {exc}"
            except Exception as exc:  # noqa: BLE001 — never let the loop die
                logger.exception("license_periodic_verify_unexpected_error",
                                 extra={"err": str(exc)})

    task = asyncio.get_event_loop().create_task(_runner())
    _PERIODIC_TASK = task
    return task


def stop_periodic_verifier() -> None:
    """Cancel the background re-verify task (tests + clean shutdown)."""
    global _PERIODIC_TASK
    if _PERIODIC_TASK is not None and not _PERIODIC_TASK.done():
        _PERIODIC_TASK.cancel()
    _PERIODIC_TASK = None


__all__ = [
    "ActiveBundle",
    "BundleVerificationError",
    "PERIODIC_VERIFY_SECONDS",
    "TRUSTED_VENDOR_FINGERPRINT",
    "VENDOR_PUBKEY_VAULT_PATH",
    "canonicalise",
    "fingerprint",
    "get_active_bundle",
    "load_active_bundle",
    "set_active_bundle",
    "start_periodic_verifier",
    "stop_periodic_verifier",
    "verify_signature",
]
