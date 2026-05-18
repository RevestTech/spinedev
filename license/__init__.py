"""
license
=======

Spine v3 feature-flag licensing subsystem (Wave 4 Squad B).

Implements design decision **#23** (``docs/V3_DESIGN_DECISIONS.md``):
feature-flag licensing as a Day-1 architectural primitive. Every feature
in the product is gated by a flag; the flags ship inside a signed
license bundle issued by the vendor; the Hub validates the Ed25519
signature on startup, periodically, and on every feature gate.

Public surface (locked for Wave 4):

    is_enabled(flag)            — bool; replaces Wave 3 Squad C stub
    quota_remaining(flag)       — int | None; remaining units this period
    invalidate_cache()          — drop quota cache after a bundle change
    record_usage(...)           — append hash-chained quota usage row
    verify_chain(...)           — replay the ledger hash chain
    load_active_bundle(...)     — startup hook: load + verify the bundle
    start_periodic_verifier(...) — background re-verify task
    status_snapshot()           — diagnostic dict for /api/v2/license

    BundleVerificationError     — stable .code on every failure mode
    ActiveBundle                — cached active bundle dataclass

Closed-source v1.0 posture (#18): this subsystem is the anti-piracy
seam. Verification happens locally so air-gapped + on-prem deployments
never need to phone home; the trust anchor is a hard-coded vendor public
key fingerprint baked into the Hub binary at build time
(``bundle_verifier.TRUSTED_VENDOR_FINGERPRINT``).

Vendor-side signing happens via ``tools/license-sign.sh`` — that script
loads the Ed25519 private key on-demand from the vendor vault (per #9 +
Part 4.3, recovered via Shamir 3-of-5 if needed), signs in memory, and
exits. The private key is **never** written to disk and never enters
this Python package.
"""

from __future__ import annotations

from license.bundle_verifier import (
    ActiveBundle,
    BundleVerificationError,
    canonicalise,
    fingerprint,
    get_active_bundle,
    load_active_bundle,
    set_active_bundle,
    start_periodic_verifier,
    stop_periodic_verifier,
    verify_signature,
)
from license.feature_flags import (
    invalidate_cache,
    is_enabled,
    quota_remaining,
    set_pool,
    status_snapshot,
)
from license.quota_ledger import GENESIS_ANCHOR_HEX, record_usage, verify_chain

__all__ = [
    # feature gates
    "is_enabled",
    "quota_remaining",
    "invalidate_cache",
    "set_pool",
    "status_snapshot",
    # bundle lifecycle
    "ActiveBundle",
    "BundleVerificationError",
    "canonicalise",
    "fingerprint",
    "get_active_bundle",
    "load_active_bundle",
    "set_active_bundle",
    "start_periodic_verifier",
    "stop_periodic_verifier",
    "verify_signature",
    # quota ledger
    "GENESIS_ANCHOR_HEX",
    "record_usage",
    "verify_chain",
]
