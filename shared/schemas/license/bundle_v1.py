"""``license-bundle-v1`` — Pydantic schema for the signed license payload.

A signed license bundle is the canonical structure the vendor ships to
each customer Hub. The wire format is:

    {
        "envelope": { ... SignedLicenseBundle ... },
    }

where the envelope wraps:

* ``payload_canonical_b64`` — base64(canonical JSON of the
  :class:`LicenseBundlePayload`). Canonicalisation matches the rules in
  :func:`license.bundle_verifier.canonicalise` (sorted keys, no
  whitespace, UTF-8). The signature covers exactly these bytes.
* ``signature_b64`` — base64 Ed25519 detached signature.
* ``signing_key_fingerprint`` — hex SHA-256 of the vendor public key
  the customer's Hub should expect; lets the Hub fail-fast if it sees
  an unknown vendor key.

The inner :class:`LicenseBundlePayload` is the actual licence content:

* ``customer`` — opaque identifier (typically the Hub's stable id).
* ``tier`` — one of the six tiers from V22's CHECK constraint.
* ``bundle_id`` — unique bundle UUID (string); becomes
  ``spine_license.bundle.id`` once persisted.
* ``issued_at`` / ``expires_at`` — UTC ISO-8601; ``expires_at=None``
  is the V22 "perpetual" sentinel.
* ``feature_flags`` — exhaustive list of ``FeatureFlag`` rows mirroring
  ``spine_license.feature_flag``. The set of flag names MUST be a
  subset of ``shared.api.middleware.feature_flag.KNOWN_FEATURE_FLAGS``
  (validated at verify time, not at parse time, because the canonical
  flag registry lives in the Hub).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

#: Wire constant; bumped on any breaking change to the payload shape.
BUNDLE_PAYLOAD_VERSION: Literal["license-bundle-v1"] = "license-bundle-v1"

#: Tier values must match V22's CHECK (spine_license.bundle.tier).
Tier = Literal["free", "founder", "team", "enterprise", "airgapped", "custom"]

#: Allowed quota units. Free-form text in V22; the Pydantic Literal here
#: is the v1 contract — adding a unit means cutting a new payload version.
QuotaUnit = Literal[
    "agents_per_month", "projects", "seats", "tokens_per_day", "runs_per_day",
]


_FORBID = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FeatureFlag(BaseModel):
    """One ``spine_license.feature_flag`` row inside the signed payload."""

    model_config = _FORBID

    flag_name: Annotated[str, Field(min_length=1, max_length=128,
        description="Stable feature identifier (must match KNOWN_FEATURE_FLAGS).")]
    enabled: bool = Field(default=False,
        description="Whether the feature is on for this bundle.")
    quota_value: Optional[int] = Field(default=None, ge=0,
        description="Numeric ceiling for metered features; None = unlimited.")
    quota_unit: Optional[QuotaUnit] = Field(default=None,
        description="Quota unit when quota_value is set.")


class LicenseBundlePayload(BaseModel):
    """The signed inner payload — the actual licence content.

    Canonicalised + signed by the vendor; verified by the Hub on
    startup, periodically, and on every feature gate evaluation per #23.
    """

    model_config = _FORBID

    payload_version: Literal["license-bundle-v1"] = BUNDLE_PAYLOAD_VERSION
    customer: Annotated[str, Field(min_length=1, max_length=256,
        description="Opaque customer identifier (typically Hub id).")]
    tier: Tier
    bundle_id: Annotated[str, Field(min_length=1, max_length=128,
        description="Unique bundle UUID; persisted as spine_license.bundle.id.")]
    issued_at: datetime = Field(...,
        description="UTC ISO-8601 issuance timestamp.")
    expires_at: Optional[datetime] = Field(default=None,
        description="UTC ISO-8601 expiry; None = perpetual.")
    feature_flags: list[FeatureFlag] = Field(default_factory=list,
        description="Per-flag enablement rows.")
    notes: Optional[str] = Field(default=None, max_length=1024,
        description="Free-form note from vendor (e.g. contract reference).")


class SignedLicenseBundle(BaseModel):
    """Outer wire envelope — what the vendor publishes + customer imports.

    The :class:`LicenseBundlePayload` is canonicalised + base64-encoded
    so the signature covers a stable byte sequence regardless of the
    transport (JSON over HTTPS, file-on-disk, etc.).
    """

    model_config = _FORBID

    payload_canonical_b64: Annotated[str, Field(min_length=1,
        description="Base64(canonical JSON of LicenseBundlePayload).")]
    signature_b64: Annotated[str, Field(min_length=1,
        description="Base64 Ed25519 detached signature over canonical bytes.")]
    signing_key_fingerprint: Annotated[str, Field(min_length=64, max_length=64,
        pattern=r"^[0-9a-f]{64}$",
        description="Hex SHA-256 of vendor Ed25519 public key.")]


__all__ = [
    "BUNDLE_PAYLOAD_VERSION",
    "FeatureFlag",
    "LicenseBundlePayload",
    "QuotaUnit",
    "SignedLicenseBundle",
    "Tier",
]
