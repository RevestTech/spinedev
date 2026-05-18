"""Pydantic schemas for Spine v3 license bundles (Wave 4 Squad B).

The signed bundle payload format is defined in :mod:`bundle_v1`. Future
bundle versions add sibling modules (``bundle_v2``, etc.); the
``payload_version`` field on the canonical envelope is the discriminator.

Per design decision #23 (``docs/V3_DESIGN_DECISIONS.md``) the license
bundle is a *special signed bundle from vendor* that reuses the same
signing primitives as the org-policy bundles in ``shared/standards/``.
"""

from __future__ import annotations

from shared.schemas.license.bundle_v1 import (
    BUNDLE_PAYLOAD_VERSION,
    FeatureFlag,
    LicenseBundlePayload,
    QuotaUnit,
    SignedLicenseBundle,
    Tier,
)

__all__ = [
    "BUNDLE_PAYLOAD_VERSION",
    "FeatureFlag",
    "LicenseBundlePayload",
    "QuotaUnit",
    "SignedLicenseBundle",
    "Tier",
]
