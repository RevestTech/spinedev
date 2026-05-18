"""``/api/v2/license`` — license + per-feature usage (#23).

The SPA renders a "license & usage" panel showing:

* The active license tier + expiry.
* Every feature flag the bundle declares + whether it's enabled.
* Per-feature usage counters so customer + sales see exactly which flags
  are being exercised (the data needed to set pricing later, per #23).

Wave 3 part 1 stubs the bundle-lookup with the in-memory feature-flag
catalog. Wave 4's ``shared.license`` package will source these from the
signed bundle + a ``spine_license.usage`` table.

Endpoints:

* ``GET /api/v2/license``         — tier, expiry, flag summary
* ``GET /api/v2/license/usage``   — per-feature usage counters

Dependencies: ``fastapi``, ``pydantic`` (already required).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from shared.api.dependencies import current_user
from shared.api.middleware.feature_flag import KNOWN_FEATURE_FLAGS, is_feature_enabled
from shared.identity.models import User

logger = logging.getLogger("spine.api.license")
router = APIRouter(prefix="/api/v2/license", tags=["license"])

LicenseTier = Literal["free", "founder", "team", "enterprise", "airgapped"]


class FlagStatus(BaseModel):
    """Per-flag status row."""

    model_config = ConfigDict(extra="forbid")
    flag: str
    enabled: bool


class LicenseSummary(BaseModel):
    """``GET /license`` envelope."""

    model_config = ConfigDict(extra="forbid")
    ok: bool = True
    tier: LicenseTier
    bundle_id: str
    expires_at: str
    signed: bool
    flags: list[FlagStatus]
    citation: Optional[str] = Field(
        default=None,
        description="Per #12 verify-class responses include a citation; here the "
        "license bundle reference (file:line or signed-bundle hash).",
    )


class UsageCounter(BaseModel):
    """Per-feature usage counter."""

    model_config = ConfigDict(extra="forbid")
    flag: str
    count: int
    last_used_at: Optional[str] = None


class UsageResponse(BaseModel):
    """``GET /license/usage`` envelope."""

    model_config = ConfigDict(extra="forbid")
    ok: bool = True
    items: list[UsageCounter]
    citation: Optional[str] = None


# Tier sourced from env-as-metadata; Wave 4 reads it from signed bundle.
_TIER: LicenseTier = (os.environ.get("SPINE_LICENSE_TIER", "free") or "free").lower()  # type: ignore[assignment]
if _TIER not in {"free", "founder", "team", "enterprise", "airgapped"}:
    _TIER = "free"  # type: ignore[assignment]


@router.get("", response_model=LicenseSummary)
async def license_summary(user: Annotated[User, Depends(current_user)]) -> LicenseSummary:
    """Active license tier + per-flag enabled/disabled view."""
    expires = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()
    flags = [FlagStatus(flag=f, enabled=is_feature_enabled(f)) for f in sorted(KNOWN_FEATURE_FLAGS)]
    return LicenseSummary(
        tier=_TIER,
        bundle_id="stub-bundle-wave3-part1",
        expires_at=expires,
        signed=False,
        flags=flags,
        citation="shared/api/routes/license.py:_TIER (Wave 4 will swap for signed-bundle citation)",
    )


@router.get("/usage", response_model=UsageResponse)
async def license_usage(user: Annotated[User, Depends(current_user)]) -> UsageResponse:
    """Per-feature usage counters.

    Wave 3 part 1 returns zeroes — the counter table lives in
    ``spine_license.usage`` (Wave 4). The shape is the durable
    contract so the SPA can render the panel today.
    """
    items = [UsageCounter(flag=f, count=0) for f in sorted(KNOWN_FEATURE_FLAGS)]
    return UsageResponse(
        items=items,
        citation="shared/api/routes/license.py:license_usage stub (counters TBD Wave 4)",
    )


__all__ = ["router", "LicenseSummary", "UsageResponse", "FlagStatus", "UsageCounter"]
