"""Tests for ``shared.identity.rbac`` and ``feature_flag_lightening``."""

from __future__ import annotations

import asyncio

import pytest

from shared.identity.feature_flag_lightening import (
    KNOWN_TIERS,
    TIER_CAPABILITIES,
    capabilities_for_tier,
    capability_level,
    diff_tiers,
    is_known_tier,
    supports,
)
from shared.identity.models import TokenClaims, User
from shared.identity.rbac import (
    AuthorizationError,
    BundlePolicyResolver,
    get_policy_resolver,
    has_any_role,
    has_group,
    has_role,
    has_scope,
    require_any_role,
    require_group,
    require_role,
    require_scope,
    set_policy_resolver,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _user_with(
    roles: list[str] | None = None,
    scopes: list[str] | None = None,
    groups: list[str] | None = None,
) -> User:
    claims = TokenClaims(
        sub="u",
        realm_access={"roles": roles or []},
        groups=groups or [],
        scope=" ".join(scopes or []),
        exp=9999999999,
        iat=1,
    )
    return User.from_claims(claims)


# ---------------------------------------------------------------------------
# User.from_claims
# ---------------------------------------------------------------------------


def test_user_from_claims_flattens_realm_and_client_roles() -> None:
    claims = TokenClaims(
        sub="u",
        realm_access={"roles": ["user", "admin"]},
        resource_access={
            "hub": {"roles": ["editor"]},
            "kg": {"roles": ["reader"]},
        },
        groups=["/eng", "/eng/backend"],
        scope="openid profile email",
        exp=9999999999,
        iat=1,
    )
    u = User.from_claims(claims)
    assert "user" in u.roles
    assert "admin" in u.roles
    assert "hub.editor" in u.roles
    assert "kg.reader" in u.roles
    assert u.groups == ["/eng", "/eng/backend"]
    assert u.scopes == ["openid", "profile", "email"]


def test_user_from_claims_deduplicates_roles() -> None:
    claims = TokenClaims(
        sub="u",
        realm_access={"roles": ["user", "user"]},
        exp=9999999999,
        iat=1,
    )
    u = User.from_claims(claims)
    assert u.roles.count("user") == 1


# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------


def test_has_role_true_and_false() -> None:
    u = _user_with(roles=["admin"])
    assert has_role(u, "admin") is True
    assert has_role(u, "missing") is False


def test_has_any_role() -> None:
    u = _user_with(roles=["editor"])
    assert has_any_role(u, ["admin", "editor"]) is True
    assert has_any_role(u, ["admin", "owner"]) is False


def test_has_scope() -> None:
    u = _user_with(scopes=["openid", "profile"])
    assert has_scope(u, "openid") is True
    assert has_scope(u, "email") is False


def test_has_group() -> None:
    u = _user_with(groups=["/eng/backend"])
    assert has_group(u, "/eng/backend") is True
    assert has_group(u, "/eng/frontend") is False


# ---------------------------------------------------------------------------
# Dependency factories
# ---------------------------------------------------------------------------


def test_require_role_passes_when_role_present() -> None:
    u = _user_with(roles=["admin"])
    dep = require_role("admin")
    result = asyncio.run(dep(user=u))
    assert result is u


def test_require_role_403s_when_role_missing() -> None:
    u = _user_with(roles=["user"])
    dep = require_role("admin")
    with pytest.raises(AuthorizationError) as exc:
        asyncio.run(dep(user=u))
    assert getattr(exc.value, "status_code", None) == 403


def test_require_any_role() -> None:
    u = _user_with(roles=["editor"])
    asyncio.run(require_any_role("admin", "editor")(user=u))
    with pytest.raises(AuthorizationError):
        asyncio.run(require_any_role("admin", "owner")(user=u))


def test_require_scope() -> None:
    u = _user_with(scopes=["openid"])
    asyncio.run(require_scope("openid")(user=u))
    with pytest.raises(AuthorizationError):
        asyncio.run(require_scope("write:projects")(user=u))


def test_require_group() -> None:
    u = _user_with(groups=["/eng"])
    asyncio.run(require_group("/eng")(user=u))
    with pytest.raises(AuthorizationError):
        asyncio.run(require_group("/finance")(user=u))


# ---------------------------------------------------------------------------
# BundlePolicyResolver swap-in
# ---------------------------------------------------------------------------


class _ExpandingResolver(BundlePolicyResolver):
    """Resolver that grants ``deploy:prod`` to anyone in /engineering/backend."""

    def effective_roles(self, user: User) -> set[str]:
        roles = set(user.roles)
        if "/engineering/backend" in user.groups:
            roles.add("deploy:prod")
        return roles


def test_policy_resolver_can_be_swapped() -> None:
    default = get_policy_resolver()
    try:
        set_policy_resolver(_ExpandingResolver())
        u = _user_with(groups=["/engineering/backend"])
        assert has_role(u, "deploy:prod") is True
    finally:
        set_policy_resolver(default)


# ---------------------------------------------------------------------------
# feature_flag_lightening
# ---------------------------------------------------------------------------


def test_known_tiers_present() -> None:
    assert set(KNOWN_TIERS) <= set(TIER_CAPABILITIES.keys())
    for t in KNOWN_TIERS:
        assert is_known_tier(t) is True
    assert is_known_tier("nonexistent") is False


def test_capabilities_returns_copy_not_reference() -> None:
    caps = capabilities_for_tier("free")
    caps["mfa"] = "required"
    fresh = capabilities_for_tier("free")
    assert fresh["mfa"] is False  # original untouched


def test_unknown_tier_defaults_to_free() -> None:
    caps = capabilities_for_tier("unknown-tier")
    assert caps["mfa"] is False
    assert caps["scim"] is False


def test_supports_for_known_capabilities() -> None:
    assert supports("free", "mfa") is False
    assert supports("founder", "mfa") is True  # "optional"
    assert supports("team", "mfa") is True  # "required"
    assert supports("free", "scim") is False
    assert supports("enterprise", "scim") is True  # "full"
    assert supports("airgapped", "social_login") is False


def test_capability_level_returns_raw_value() -> None:
    assert capability_level("founder", "mfa") == "optional"
    assert capability_level("team", "scim") == "basic"
    assert capability_level("enterprise", "scim") == "full"
    assert capability_level("enterprise", "realms") == "multi"


def test_tier_ladder_monotonically_adds_capabilities() -> None:
    """Higher tiers should support at least every capability lower tiers do."""
    ladder = ("free", "founder", "team", "enterprise")
    capabilities_to_check = [
        "mfa",
        "social_login",
        "idp_federation",
        "scim",
        "audit_export",
        "hub_ui_groups_admin",
    ]
    for cap in capabilities_to_check:
        prev_supported = False
        for tier in ladder:
            now_supported = supports(tier, cap)
            if prev_supported and not now_supported:
                raise AssertionError(
                    f"Capability {cap!r} regresses from previous tier at {tier}"
                )
            prev_supported = prev_supported or now_supported


def test_diff_tiers_reports_only_differences() -> None:
    d = diff_tiers("free", "enterprise")
    assert "mfa" in d
    assert d["mfa"] == (False, "required")
    # Capabilities that are equal across tiers should NOT appear
    for k, (a, b) in d.items():
        assert a != b


def test_airgapped_disables_social_login_but_keeps_scim() -> None:
    assert supports("airgapped", "social_login") is False
    assert supports("airgapped", "scim") is True
    assert capability_level("airgapped", "scim") == "full"
