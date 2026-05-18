"""
shared/identity/feature_flag_lightening.py
==========================================

Tier-based simplification of Keycloak capabilities — implements Spine v3
design decision #25 ("Identity = Keycloak embedded by default, feature-flag
lightening per tier") in concert with #14 ("Target market = ALL three
segments").

The same Keycloak container ships at every tier. What changes per tier is
**which Keycloak capabilities are exposed in the Hub UI / Day-0 wizard /
bundle policy**. The capability matrix here is the canonical lookup. It is
read by:

* Day-0 install wizard — to choose which realm features to surface
* Hub UI — to gate menu items (SCIM tab hidden on free, etc.)
* Bundle validator — to refuse policies that demand a capability the tier
  doesn't include

This module is intentionally **data-only**. It does NOT enforce licensing
(that's ``shared/license/`` in Wave 1+). It does NOT call into Keycloak
(``shared/identity/keycloak_client.py`` does that). It just answers the
question "what does this tier support?".

Per #14, tier identity is hierarchical:

    free → founder → team → enterprise

and ``airgapped`` is a sibling-of-enterprise variant (#17). Higher tiers
inherit all capabilities of lower tiers (with overrides).
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

# Canonical tier ladder (excluding airgapped — handled separately)
TIER_LADDER: tuple[str, ...] = ("free", "founder", "team", "enterprise")
KNOWN_TIERS: tuple[str, ...] = (*TIER_LADDER, "airgapped")

# Capability values use a small vocabulary:
#   False           — not available
#   True            — available, no further configuration
#   "optional"      — surfaced but customer can disable
#   "required"      — surfaced and customer must enable
#   "basic" / "full"— graduated capability (e.g. SCIM)
#   "single"/"multi"— count-style capability (e.g. IdP federation)
#   int / "multi"   — for ``realms`` / ``clients``

# ---------------------------------------------------------------------------
# Per-tier capability matrix
# ---------------------------------------------------------------------------

TIER_CAPABILITIES: dict[str, dict[str, Any]] = {
    "free": {
        # Realm shape
        "realms": 1,
        "clients_per_realm": 1,
        # Authentication
        "username_password": True,
        "mfa": False,
        "passwordless": False,
        # Federation / brokering
        "social_login": False,
        "idp_federation": False,
        "saml_inbound": False,
        # Provisioning
        "scim": False,
        "user_self_registration": True,
        # Policy
        "password_policy_advanced": False,
        "session_idle_timeout_min": 30,
        # Theming + branding
        "custom_themes": False,
        "custom_email_templates": False,
        # Auditing + export
        "audit_export": False,
        "event_streaming": False,
        # Hub surfaces gated by tier
        "hub_ui_groups_admin": False,
        "hub_ui_scim_tab": False,
        "hub_ui_idp_federation_tab": False,
        "hub_ui_audit_export_tab": False,
    },
    "founder": {
        "realms": 1,
        "clients_per_realm": 5,
        "username_password": True,
        "mfa": "optional",
        "passwordless": "optional",
        "social_login": True,
        "idp_federation": "single",
        "saml_inbound": "single",
        "scim": False,
        "user_self_registration": True,
        "password_policy_advanced": True,
        "session_idle_timeout_min": 60,
        "custom_themes": False,
        "custom_email_templates": True,
        "audit_export": False,
        "event_streaming": False,
        "hub_ui_groups_admin": True,
        "hub_ui_scim_tab": False,
        "hub_ui_idp_federation_tab": True,
        "hub_ui_audit_export_tab": False,
    },
    "team": {
        "realms": 1,
        "clients_per_realm": 25,
        "username_password": True,
        "mfa": "required",
        "passwordless": "optional",
        "social_login": True,
        "idp_federation": "multi",
        "saml_inbound": "multi",
        "scim": "basic",
        "user_self_registration": "optional",
        "password_policy_advanced": True,
        "session_idle_timeout_min": 120,
        "custom_themes": True,
        "custom_email_templates": True,
        "audit_export": "basic",
        "event_streaming": False,
        "hub_ui_groups_admin": True,
        "hub_ui_scim_tab": True,
        "hub_ui_idp_federation_tab": True,
        "hub_ui_audit_export_tab": True,
    },
    "enterprise": {
        "realms": "multi",
        "clients_per_realm": "multi",
        "username_password": True,
        "mfa": "required",
        "passwordless": "optional",
        "social_login": True,
        "idp_federation": "multi",
        "saml_inbound": "multi",
        "scim": "full",
        "user_self_registration": "optional",
        "password_policy_advanced": True,
        "session_idle_timeout_min": 240,
        "custom_themes": True,
        "custom_email_templates": True,
        "audit_export": "full",
        "event_streaming": True,
        "hub_ui_groups_admin": True,
        "hub_ui_scim_tab": True,
        "hub_ui_idp_federation_tab": True,
        "hub_ui_audit_export_tab": True,
    },
    "airgapped": {
        # Airgapped == enterprise capabilities except no outbound social login.
        "realms": 1,
        "clients_per_realm": "multi",
        "username_password": True,
        "mfa": "required",
        "passwordless": "optional",
        "social_login": False,
        "idp_federation": "multi",
        "saml_inbound": "multi",
        "scim": "full",
        "user_self_registration": False,
        "password_policy_advanced": True,
        "session_idle_timeout_min": 240,
        "custom_themes": True,
        "custom_email_templates": True,
        "audit_export": "full",
        "event_streaming": True,
        "hub_ui_groups_admin": True,
        "hub_ui_scim_tab": True,
        "hub_ui_idp_federation_tab": True,
        "hub_ui_audit_export_tab": True,
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def capabilities_for_tier(tier: str) -> dict[str, Any]:
    """Return a *copy* of the capability dict for ``tier``.

    Returns the ``free`` matrix when ``tier`` is unrecognized — fail-closed
    posture: an unknown tier should never accidentally unlock paid features.
    Callers that care about validity should use ``is_known_tier`` first.
    """
    if tier not in TIER_CAPABILITIES:
        return deepcopy(TIER_CAPABILITIES["free"])
    return deepcopy(TIER_CAPABILITIES[tier])


def is_known_tier(tier: str) -> bool:
    """True if ``tier`` is one of the canonical tiers."""
    return tier in KNOWN_TIERS


def supports(tier: str, capability: str) -> bool:
    """Cheap truthiness check for whether a tier supports a capability.

    A capability is considered "supported" when its value is truthy AND not
    explicitly ``False``. ``"optional"`` / ``"required"`` / ``"basic"`` /
    ``"full"`` / ``"single"`` / ``"multi"`` / non-zero ``int`` all count.
    """
    caps = capabilities_for_tier(tier)
    value = caps.get(capability, False)
    if value is False or value is None:
        return False
    if value == 0 or value == "":
        return False
    return True


def capability_level(tier: str, capability: str) -> Any:
    """Return the raw capability value for ``tier``/``capability``."""
    return capabilities_for_tier(tier).get(capability, False)


def diff_tiers(tier_a: str, tier_b: str) -> dict[str, tuple[Any, Any]]:
    """Return ``{capability: (a_value, b_value)}`` for every differing key.

    Useful for the Hub's "upgrade to unlock" UI: list the features a customer
    would gain by moving from ``tier_a`` to ``tier_b``.
    """
    caps_a = capabilities_for_tier(tier_a)
    caps_b = capabilities_for_tier(tier_b)
    keys = set(caps_a.keys()) | set(caps_b.keys())
    return {
        k: (caps_a.get(k), caps_b.get(k))
        for k in sorted(keys)
        if caps_a.get(k) != caps_b.get(k)
    }
