"""Tests for ``license.feature_flags``."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from license import bundle_verifier, feature_flags
from license.bundle_verifier import ActiveBundle
from license.feature_flags import (
    invalidate_cache,
    is_enabled,
    quota_remaining,
    status_snapshot,
)
from shared.schemas.license import FeatureFlag, LicenseBundlePayload


def _install(flags: list[FeatureFlag], *, expires_at=None) -> None:
    payload = LicenseBundlePayload(
        customer="acme", tier="team", bundle_id="b1",
        issued_at=datetime.now(timezone.utc), expires_at=expires_at,
        feature_flags=flags,
    )
    bundle_verifier.set_active_bundle(ActiveBundle(payload=payload))


def test_no_bundle_fails_closed_except_inspector() -> None:
    """When no bundle is loaded, every gate fails except license_inspector."""
    bundle_verifier.set_active_bundle(None)
    assert is_enabled("federation") is False
    assert is_enabled("license_inspector") is True


def test_unknown_flag_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        is_enabled("definitely-not-a-real-flag")


def test_enabled_flag_returns_true() -> None:
    _install([FeatureFlag(flag_name="federation", enabled=True)])
    assert is_enabled("federation") is True


def test_explicitly_disabled_flag_returns_false() -> None:
    _install([FeatureFlag(flag_name="federation", enabled=False)])
    assert is_enabled("federation") is False


def test_missing_from_bundle_fails_closed() -> None:
    """If a known flag isn't even listed in the bundle, it's off."""
    _install([FeatureFlag(flag_name="federation", enabled=True)])
    assert is_enabled("integration_vanta") is False


def test_signature_invalidation_disables_all_gates() -> None:
    payload = LicenseBundlePayload(
        customer="acme", tier="team", bundle_id="b1",
        issued_at=datetime.now(timezone.utc),
        feature_flags=[FeatureFlag(flag_name="federation", enabled=True)],
    )
    bundle_verifier.set_active_bundle(
        ActiveBundle(payload=payload, signature_ok=False),
    )
    assert is_enabled("federation") is False
    assert is_enabled("license_inspector") is True  # fail-open for upgrade UI


def test_quota_remaining_returns_none_for_unmetered() -> None:
    _install([FeatureFlag(flag_name="federation", enabled=True)])

    async def _run():
        return await quota_remaining("federation")

    assert asyncio.run(_run()) is None


def test_quota_remaining_subtracts_used_value(mock_pool) -> None:
    _install([FeatureFlag(flag_name="role_devops", enabled=True,
                          quota_value=100, quota_unit="agents_per_month")])
    mock_pool.script_rows([{"sum": 25}])

    async def _run():
        return await quota_remaining("role_devops")

    assert asyncio.run(_run()) == 75


def test_quota_remaining_clamps_to_zero(mock_pool) -> None:
    _install([FeatureFlag(flag_name="role_devops", enabled=True,
                          quota_value=10, quota_unit="agents_per_month")])
    mock_pool.script_rows([{"sum": 999}])

    async def _run():
        return await quota_remaining("role_devops")

    assert asyncio.run(_run()) == 0


def test_quota_remaining_cache_hit(mock_pool) -> None:
    _install([FeatureFlag(flag_name="role_devops", enabled=True,
                          quota_value=100, quota_unit="agents_per_month")])
    mock_pool.script_rows([{"sum": 10}])

    async def _twice():
        a = await quota_remaining("role_devops")
        b = await quota_remaining("role_devops")
        return a, b

    a, b = asyncio.run(_twice())
    assert a == b == 90
    # Second call should be served from cache → only one DB read recorded.
    assert len(mock_pool.queries) == 1


def test_status_snapshot_no_bundle() -> None:
    bundle_verifier.set_active_bundle(None)
    snap = status_snapshot()
    assert snap["loaded"] is False
    assert snap["flags"] == []


def test_status_snapshot_with_bundle() -> None:
    _install([FeatureFlag(flag_name="federation", enabled=True)])
    snap = status_snapshot()
    assert snap["loaded"] is True
    assert snap["tier"] == "team"
    assert any(f["flag_name"] == "federation" for f in snap["flags"])


def test_invalidate_cache_clears_quota_cache(mock_pool) -> None:
    _install([FeatureFlag(flag_name="role_devops", enabled=True,
                          quota_value=50, quota_unit="agents_per_month")])
    mock_pool.script_rows([{"sum": 5}])
    mock_pool.script_rows([{"sum": 6}])

    async def _seq():
        a = await quota_remaining("role_devops")
        invalidate_cache()
        b = await quota_remaining("role_devops")
        return a, b

    a, b = asyncio.run(_seq())
    assert a == 45
    assert b == 44  # fresh read after invalidate
