"""
Tests for secrets rotation module.

Covers:
    - RotationPolicy creation and validation
    - RotationStatus enum values
    - check_rotation_status with various date scenarios
    - get_rotation_policies default policies
    - rotate_secret async placeholder
    - check_all_rotations bulk status checking
    - Edge cases: never-rotated, boundary dates, etc.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta

from tron.infra.secrets.rotation import (
    RotationPolicy,
    RotationStatus,
    check_rotation_status,
    get_rotation_policies,
    rotate_secret,
    check_all_rotations,
)


# ---------------------------------------------------------------------------
# RotationPolicy Tests
# ---------------------------------------------------------------------------


class TestRotationPolicy:
    """Tests for RotationPolicy dataclass."""

    def test_create_policy_with_required_fields(self) -> None:
        """Create a policy with only required fields."""
        policy = RotationPolicy(
            secret_path="db/password",
            rotation_interval_days=90,
        )
        assert policy.secret_path == "db/password"
        assert policy.rotation_interval_days == 90
        assert policy.last_rotated is None
        assert policy.notify_before_days == 7

    def test_create_policy_with_all_fields(self) -> None:
        """Create a policy with all fields specified."""
        now = datetime.utcnow()
        policy = RotationPolicy(
            secret_path="auth/master-key",
            rotation_interval_days=365,
            last_rotated=now,
            notify_before_days=30,
        )
        assert policy.secret_path == "auth/master-key"
        assert policy.rotation_interval_days == 365
        assert policy.last_rotated == now
        assert policy.notify_before_days == 30

    def test_policy_with_zero_rotation_interval_fails(self) -> None:
        """Reject policies with zero or negative rotation_interval_days."""
        with pytest.raises(ValueError, match="rotation_interval_days must be positive"):
            RotationPolicy(
                secret_path="test/secret",
                rotation_interval_days=0,
            )

    def test_policy_with_negative_rotation_interval_fails(self) -> None:
        """Reject policies with negative rotation_interval_days."""
        with pytest.raises(ValueError, match="rotation_interval_days must be positive"):
            RotationPolicy(
                secret_path="test/secret",
                rotation_interval_days=-1,
            )

    def test_policy_with_negative_notify_days_fails(self) -> None:
        """Reject policies with negative notify_before_days."""
        with pytest.raises(ValueError, match="notify_before_days cannot be negative"):
            RotationPolicy(
                secret_path="test/secret",
                rotation_interval_days=90,
                notify_before_days=-1,
            )

    def test_policy_with_notify_exceeding_interval_fails(self) -> None:
        """Reject if notify_before_days exceeds rotation_interval_days."""
        with pytest.raises(
            ValueError, match="notify_before_days cannot exceed rotation_interval_days"
        ):
            RotationPolicy(
                secret_path="test/secret",
                rotation_interval_days=90,
                notify_before_days=100,
            )

    def test_policy_rotation_due_date_when_never_rotated(self) -> None:
        """rotation_due_date is None if last_rotated is None."""
        policy = RotationPolicy(
            secret_path="test/secret",
            rotation_interval_days=90,
            last_rotated=None,
        )
        assert policy.rotation_due_date is None

    def test_policy_rotation_due_date_calculation(self) -> None:
        """rotation_due_date is last_rotated + rotation_interval_days."""
        now = datetime.utcnow()
        policy = RotationPolicy(
            secret_path="test/secret",
            rotation_interval_days=90,
            last_rotated=now,
        )
        expected_due = now + timedelta(days=90)
        assert policy.rotation_due_date == expected_due

    def test_policy_notification_threshold_when_never_rotated(self) -> None:
        """notification_threshold is None if last_rotated is None."""
        policy = RotationPolicy(
            secret_path="test/secret",
            rotation_interval_days=90,
            last_rotated=None,
            notify_before_days=7,
        )
        assert policy.notification_threshold is None

    def test_policy_notification_threshold_calculation(self) -> None:
        """notification_threshold is rotation_due_date - notify_before_days."""
        now = datetime.utcnow()
        policy = RotationPolicy(
            secret_path="test/secret",
            rotation_interval_days=90,
            last_rotated=now,
            notify_before_days=7,
        )
        expected_threshold = now + timedelta(days=90 - 7)
        assert policy.notification_threshold == expected_threshold


# ---------------------------------------------------------------------------
# RotationStatus Enum Tests
# ---------------------------------------------------------------------------


class TestRotationStatus:
    """Tests for RotationStatus enum."""

    def test_status_current_value(self) -> None:
        """RotationStatus.CURRENT has correct value."""
        assert RotationStatus.CURRENT.value == "current"

    def test_status_expiring_soon_value(self) -> None:
        """RotationStatus.EXPIRING_SOON has correct value."""
        assert RotationStatus.EXPIRING_SOON.value == "expiring_soon"

    def test_status_expired_value(self) -> None:
        """RotationStatus.EXPIRED has correct value."""
        assert RotationStatus.EXPIRED.value == "expired"

    def test_status_rotation_failed_value(self) -> None:
        """RotationStatus.ROTATION_FAILED has correct value."""
        assert RotationStatus.ROTATION_FAILED.value == "rotation_failed"

    def test_all_status_values_present(self) -> None:
        """All four status values are defined."""
        statuses = {s.value for s in RotationStatus}
        assert statuses == {"current", "expiring_soon", "expired", "rotation_failed"}


# ---------------------------------------------------------------------------
# check_rotation_status Tests
# ---------------------------------------------------------------------------


class TestCheckRotationStatus:
    """Tests for check_rotation_status function."""

    def test_status_expired_when_never_rotated(self) -> None:
        """Secret with last_rotated=None is EXPIRED."""
        policy = RotationPolicy(
            secret_path="test/secret",
            rotation_interval_days=90,
            last_rotated=None,
        )
        status = check_rotation_status(policy)
        assert status == RotationStatus.EXPIRED

    def test_status_current_when_just_rotated(self) -> None:
        """Secret rotated just now should be CURRENT."""
        now = datetime.utcnow()
        policy = RotationPolicy(
            secret_path="test/secret",
            rotation_interval_days=90,
            last_rotated=now,
            notify_before_days=7,
        )
        status = check_rotation_status(policy)
        assert status == RotationStatus.CURRENT

    def test_status_current_shortly_after_rotation(self) -> None:
        """Secret rotated a few days ago should be CURRENT."""
        now = datetime.utcnow()
        rotated = now - timedelta(days=10)
        policy = RotationPolicy(
            secret_path="test/secret",
            rotation_interval_days=90,
            last_rotated=rotated,
            notify_before_days=7,
        )
        status = check_rotation_status(policy)
        assert status == RotationStatus.CURRENT

    def test_status_expiring_soon_within_notification_window(self) -> None:
        """Secret within notification window should be EXPIRING_SOON."""
        now = datetime.utcnow()
        # Rotated 86 days ago: due in 4 days, notification threshold in 3 days
        rotated = now - timedelta(days=86)
        policy = RotationPolicy(
            secret_path="test/secret",
            rotation_interval_days=90,
            last_rotated=rotated,
            notify_before_days=7,
        )
        status = check_rotation_status(policy)
        assert status == RotationStatus.EXPIRING_SOON

    def test_status_expired_on_due_date(self) -> None:
        """Secret on its due date should be EXPIRED."""
        now = datetime.utcnow()
        rotated = now - timedelta(days=90)
        policy = RotationPolicy(
            secret_path="test/secret",
            rotation_interval_days=90,
            last_rotated=rotated,
            notify_before_days=7,
        )
        status = check_rotation_status(policy)
        assert status == RotationStatus.EXPIRED

    def test_status_expired_past_due_date(self) -> None:
        """Secret past its due date should be EXPIRED."""
        now = datetime.utcnow()
        rotated = now - timedelta(days=100)
        policy = RotationPolicy(
            secret_path="test/secret",
            rotation_interval_days=90,
            last_rotated=rotated,
            notify_before_days=7,
        )
        status = check_rotation_status(policy)
        assert status == RotationStatus.EXPIRED

    def test_status_boundary_just_before_notification_threshold(self) -> None:
        """Secret just before notification window should be CURRENT."""
        now = datetime.utcnow()
        # Rotated 82 days ago: due in 8 days, threshold starts at 83 days
        # 82 days < 83 days threshold → CURRENT
        rotated = now - timedelta(days=82)
        policy = RotationPolicy(
            secret_path="test/secret",
            rotation_interval_days=90,
            last_rotated=rotated,
            notify_before_days=7,
        )
        status = check_rotation_status(policy)
        assert status == RotationStatus.CURRENT

    def test_status_boundary_exactly_at_notification_threshold(self) -> None:
        """Secret exactly at notification threshold should be EXPIRING_SOON."""
        now = datetime.utcnow()
        rotated = now - timedelta(days=83)
        policy = RotationPolicy(
            secret_path="test/secret",
            rotation_interval_days=90,
            last_rotated=rotated,
            notify_before_days=7,
        )
        status = check_rotation_status(policy)
        assert status == RotationStatus.EXPIRING_SOON

    def test_status_with_different_notify_before_days(self) -> None:
        """Notification window respects custom notify_before_days."""
        now = datetime.utcnow()
        # Rotated 175 days ago: due in 5 days (with 180-day interval)
        rotated = now - timedelta(days=175)
        policy = RotationPolicy(
            secret_path="auth/master-key",
            rotation_interval_days=180,
            last_rotated=rotated,
            notify_before_days=30,
        )
        status = check_rotation_status(policy)
        assert status == RotationStatus.EXPIRING_SOON


# ---------------------------------------------------------------------------
# get_rotation_policies Tests
# ---------------------------------------------------------------------------


class TestGetRotationPolicies:
    """Tests for get_rotation_policies function."""

    def test_returns_list_of_policies(self) -> None:
        """get_rotation_policies returns a list."""
        policies = get_rotation_policies()
        assert isinstance(policies, list)
        assert len(policies) > 0

    def test_returns_six_policies(self) -> None:
        """get_rotation_policies returns exactly 6 policies."""
        policies = get_rotation_policies()
        assert len(policies) == 6

    def test_all_policies_are_rotation_policy_objects(self) -> None:
        """All returned items are RotationPolicy instances."""
        policies = get_rotation_policies()
        for policy in policies:
            assert isinstance(policy, RotationPolicy)

    def test_has_db_password_policy(self) -> None:
        """Policy for db/password exists."""
        policies = get_rotation_policies()
        db_policies = [p for p in policies if p.secret_path == "db/password"]
        assert len(db_policies) == 1
        assert db_policies[0].rotation_interval_days == 90
        assert db_policies[0].notify_before_days == 7

    def test_has_redis_password_policy(self) -> None:
        """Policy for redis/password exists."""
        policies = get_rotation_policies()
        redis_policies = [p for p in policies if p.secret_path == "redis/password"]
        assert len(redis_policies) == 1
        assert redis_policies[0].rotation_interval_days == 90
        assert redis_policies[0].notify_before_days == 7

    def test_has_auth_secret_key_policy(self) -> None:
        """Policy for auth/secret-key exists."""
        policies = get_rotation_policies()
        policies_list = [p for p in policies if p.secret_path == "auth/secret-key"]
        assert len(policies_list) == 1
        assert policies_list[0].rotation_interval_days == 180
        assert policies_list[0].notify_before_days == 14

    def test_has_auth_jwt_secret_policy(self) -> None:
        """Policy for auth/jwt-secret exists."""
        policies = get_rotation_policies()
        policies_list = [p for p in policies if p.secret_path == "auth/jwt-secret"]
        assert len(policies_list) == 1
        assert policies_list[0].rotation_interval_days == 180
        assert policies_list[0].notify_before_days == 14

    def test_has_auth_master_key_policy(self) -> None:
        """Policy for auth/master-key exists."""
        policies = get_rotation_policies()
        policies_list = [p for p in policies if p.secret_path == "auth/master-key"]
        assert len(policies_list) == 1
        assert policies_list[0].rotation_interval_days == 365
        assert policies_list[0].notify_before_days == 30

    def test_has_encryption_master_key_policy(self) -> None:
        """Policy for encryption/master-key exists."""
        policies = get_rotation_policies()
        policies_list = [
            p for p in policies if p.secret_path == "encryption/master-key"
        ]
        assert len(policies_list) == 1
        assert policies_list[0].rotation_interval_days == 365
        assert policies_list[0].notify_before_days == 30

    def test_all_policies_start_with_no_rotation_date(self) -> None:
        """All default policies have last_rotated=None."""
        policies = get_rotation_policies()
        for policy in policies:
            assert policy.last_rotated is None

    def test_all_policies_have_valid_notify_settings(self) -> None:
        """All policies have valid notify_before_days."""
        policies = get_rotation_policies()
        for policy in policies:
            assert policy.notify_before_days >= 0
            assert policy.notify_before_days <= policy.rotation_interval_days

    def test_policies_are_independent_instances(self) -> None:
        """Each call returns new policy instances."""
        policies1 = get_rotation_policies()
        policies2 = get_rotation_policies()
        assert policies1 is not policies2
        for p1, p2 in zip(policies1, policies2):
            assert p1 is not p2


# ---------------------------------------------------------------------------
# rotate_secret Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRotateSecret:
    """Tests for rotate_secret async function."""

    async def test_rotate_secret_returns_true(self) -> None:
        """rotate_secret returns True (placeholder success)."""
        result = await rotate_secret("db/password")
        assert result is True

    async def test_rotate_secret_accepts_various_paths(self) -> None:
        """rotate_secret accepts different secret paths."""
        paths = [
            "db/password",
            "auth/jwt-secret",
            "encryption/master-key",
            "redis/password",
        ]
        for path in paths:
            result = await rotate_secret(path)
            assert result is True

    async def test_rotate_secret_is_idempotent(self) -> None:
        """Multiple calls to rotate_secret all return True."""
        result1 = await rotate_secret("test/secret")
        result2 = await rotate_secret("test/secret")
        assert result1 is True
        assert result2 is True


# ---------------------------------------------------------------------------
# check_all_rotations Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCheckAllRotations:
    """Tests for check_all_rotations async function."""

    async def test_returns_dict(self) -> None:
        """check_all_rotations returns a dict."""
        result = await check_all_rotations()
        assert isinstance(result, dict)

    async def test_returns_status_for_all_secrets(self) -> None:
        """check_all_rotations includes all default secrets."""
        result = await check_all_rotations()
        expected_paths = {
            "db/password",
            "redis/password",
            "auth/secret-key",
            "auth/jwt-secret",
            "auth/master-key",
            "encryption/master-key",
        }
        assert set(result.keys()) == expected_paths

    async def test_all_values_are_rotation_status(self) -> None:
        """All values in the result dict are RotationStatus enums."""
        result = await check_all_rotations()
        for status in result.values():
            assert isinstance(status, RotationStatus)

    async def test_all_secrets_are_expired_by_default(self) -> None:
        """All default policies are EXPIRED (never rotated)."""
        result = await check_all_rotations()
        for status in result.values():
            assert status == RotationStatus.EXPIRED

    async def test_result_includes_db_password(self) -> None:
        """Result includes db/password status."""
        result = await check_all_rotations()
        assert "db/password" in result
        assert isinstance(result["db/password"], RotationStatus)

    async def test_result_includes_encryption_master_key(self) -> None:
        """Result includes encryption/master-key status."""
        result = await check_all_rotations()
        assert "encryption/master-key" in result
        assert isinstance(result["encryption/master-key"], RotationStatus)

    async def test_result_dict_size_matches_policies(self) -> None:
        """Result dict has exactly as many entries as get_rotation_policies."""
        policies = get_rotation_policies()
        result = await check_all_rotations()
        assert len(result) == len(policies)
