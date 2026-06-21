"""
Secrets rotation management for Tron.

Provides policies, status tracking, and rotation orchestration for secrets
stored in the keyvault.

Features:
    - RotationPolicy: Define when secrets should be rotated
    - RotationStatus: Check the current status of a secret
    - get_rotation_policies(): Default rotation schedules for all Tron secrets
    - check_rotation_status(): Determine if a secret needs rotation
    - rotate_secret(): Request rotation of a secret
    - check_all_rotations(): Bulk status check across all secrets
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RotationStatus(Enum):
    """Status of a secret relative to its rotation policy."""

    CURRENT = "current"
    """Secret has been rotated recently and does not need rotation."""

    EXPIRING_SOON = "expiring_soon"
    """Secret is approaching its rotation date."""

    EXPIRED = "expired"
    """Secret has passed its rotation date and needs rotation immediately."""

    ROTATION_FAILED = "rotation_failed"
    """Previous rotation attempt failed."""


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------


@dataclass
class RotationPolicy:
    """
    Rotation policy for a secret.

    Attributes:
        secret_path: Path to the secret in the vault (e.g., "db/password")
        rotation_interval_days: Days between rotations
        last_rotated: Datetime of the last successful rotation (None if never rotated)
        notify_before_days: Days before expiration to send notifications (default: 7)
    """

    secret_path: str
    rotation_interval_days: int
    last_rotated: Optional[datetime] = None
    notify_before_days: int = 7

    def __post_init__(self) -> None:
        """Validate policy on initialization."""
        if self.rotation_interval_days <= 0:
            raise ValueError("rotation_interval_days must be positive")
        if self.notify_before_days < 0:
            raise ValueError("notify_before_days cannot be negative")
        if self.notify_before_days > self.rotation_interval_days:
            raise ValueError("notify_before_days cannot exceed rotation_interval_days")

    @property
    def rotation_due_date(self) -> Optional[datetime]:
        """Calculate when the secret's rotation is due."""
        if self.last_rotated is None:
            return None
        return self.last_rotated + timedelta(days=self.rotation_interval_days)

    @property
    def notification_threshold(self) -> Optional[datetime]:
        """Calculate when to start sending rotation notifications."""
        due = self.rotation_due_date
        if due is None:
            return None
        return due - timedelta(days=self.notify_before_days)


# ---------------------------------------------------------------------------
# Rotation Status Checking
# ---------------------------------------------------------------------------


def check_rotation_status(policy: RotationPolicy) -> RotationStatus:
    """
    Check the rotation status of a secret given its policy.

    Logic:
        1. If last_rotated is None → EXPIRED (never rotated, treat as expired)
        2. If current time >= rotation_due_date → EXPIRED
        3. If current time >= notification_threshold → EXPIRING_SOON
        4. Otherwise → CURRENT

    Args:
        policy: The rotation policy to check

    Returns:
        The current RotationStatus
    """
    now = datetime.utcnow()

    # If never rotated, it's expired
    if policy.last_rotated is None:
        logger.warning(
            "Secret '%s' has never been rotated (last_rotated is None). "
            "Status: EXPIRED",
            policy.secret_path,
        )
        return RotationStatus.EXPIRED

    due_date = policy.rotation_due_date
    notification_threshold = policy.notification_threshold

    # Check if rotation is overdue
    if now >= due_date:
        logger.warning(
            "Secret '%s' is EXPIRED. Due date: %s, current time: %s",
            policy.secret_path,
            due_date,
            now,
        )
        return RotationStatus.EXPIRED

    # Check if we should start notifying
    if notification_threshold and now >= notification_threshold:
        logger.info(
            "Secret '%s' is EXPIRING_SOON. Due date: %s, current time: %s",
            policy.secret_path,
            due_date,
            now,
        )
        return RotationStatus.EXPIRING_SOON

    # Otherwise, the secret is current
    logger.debug(
        "Secret '%s' is CURRENT. Due date: %s, current time: %s",
        policy.secret_path,
        due_date,
        now,
    )
    return RotationStatus.CURRENT


# ---------------------------------------------------------------------------
# Default Rotation Policies
# ---------------------------------------------------------------------------


def get_rotation_policies() -> list[RotationPolicy]:
    """
    Get the default rotation policies for all Tron secrets.

    These policies define the rotation schedule for critical infrastructure
    secrets managed by Tron.

    Returns:
        List of RotationPolicy objects with sensible defaults:
            - db/password: 90 days
            - redis/password: 90 days
            - auth/secret-key: 180 days
            - auth/jwt-secret: 180 days
            - auth/master-key: 365 days
            - encryption/master-key: 365 days
    """
    return [
        RotationPolicy(
            secret_path="db/password",
            rotation_interval_days=90,
            notify_before_days=7,
        ),
        RotationPolicy(
            secret_path="redis/password",
            rotation_interval_days=90,
            notify_before_days=7,
        ),
        RotationPolicy(
            secret_path="auth/secret-key",
            rotation_interval_days=180,
            notify_before_days=14,
        ),
        RotationPolicy(
            secret_path="auth/jwt-secret",
            rotation_interval_days=180,
            notify_before_days=14,
        ),
        RotationPolicy(
            secret_path="auth/master-key",
            rotation_interval_days=365,
            notify_before_days=30,
        ),
        RotationPolicy(
            secret_path="encryption/master-key",
            rotation_interval_days=365,
            notify_before_days=30,
        ),
    ]


# ---------------------------------------------------------------------------
# Rotation Actions
# ---------------------------------------------------------------------------


async def rotate_secret(secret_path: str) -> bool:
    """
    Request rotation of a secret.

    This is a placeholder that logs the rotation intent. In production,
    this would integrate with the vault backend (KMac or HashiCorp) to
    actually rotate the secret.

    Args:
        secret_path: Path to the secret to rotate (e.g., "db/password")

    Returns:
        True if rotation was requested successfully, False otherwise

    Note:
        Actual vault-specific rotation logic would be implemented here:
        - KMac Vault: POST /rotate/{secret_path}
        - HashiCorp Vault: POST /v1/sys/rotate/{secret_path}
    """
    logger.info(
        "Rotation requested for secret: %s. "
        "Note: This is a placeholder. Actual rotation is vault-specific.",
        secret_path,
    )
    # Placeholder always returns True (successful intent logging)
    return True


async def check_all_rotations() -> dict[str, RotationStatus]:
    """
    Check rotation status for all default Tron secrets.

    This performs a bulk check of all secrets defined in get_rotation_policies(),
    returning a mapping of secret path to its current rotation status.

    Returns:
        Dict mapping secret_path (str) → RotationStatus
    """
    policies = get_rotation_policies()
    status_map: dict[str, RotationStatus] = {}

    for policy in policies:
        status = check_rotation_status(policy)
        status_map[policy.secret_path] = status
        logger.debug("Rotation status check: %s → %s", policy.secret_path, status.value)

    return status_map
