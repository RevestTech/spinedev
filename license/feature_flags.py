"""``is_enabled(flag)`` + ``quota_remaining(flag)`` — the per-gate hot path.

This module is the *real* implementation that replaces the Wave 3 Squad C
stub in :mod:`shared.api.middleware.feature_flag`. The stub's contract is
preserved exactly:

* ``is_enabled(flag) -> bool`` — synchronous; returns True/False per the
  active bundle. Unknown flags raise ``KeyError`` so typos crash loud.
* ``quota_remaining(flag) -> int | None`` — synchronous; None for
  unmetered flags, otherwise ``quota_value - used_value`` (clamped to 0).
* ``invalidate_cache()`` — drops the in-process feature-map cache; the
  Hub admin UI calls it after installing a new bundle.

The hot path reads exclusively from :data:`license.bundle_verifier._ACTIVE`
(populated by :func:`load_active_bundle` at startup + periodic re-verify).
We never hit Postgres on the per-gate path — even sub-millisecond round
trips would add observable latency to every API call.

Quota usage counters DO hit Postgres on write (see
:mod:`license.quota_ledger`), but the read side here uses an
async-refresh cache keyed by ``(flag_name, period_start)`` with a
``CACHE_TTL_SECONDS`` (default 60s) freshness window. A stale read
results at worst in a 60-second over-grant — by design; quotas are
billing primitives, not security primitives.

Per #23 *every* feature has a flag; ``KNOWN_FEATURE_FLAGS`` (from
``shared.api.middleware.feature_flag``) is the canonical registry.
The bundle MAY omit a flag — in that case the gate fails closed
("if vendor didn't grant it, you don't have it").
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

from license.bundle_verifier import (
    ActiveBundle,
    BundleVerificationError,
    get_active_bundle,
)

logger = logging.getLogger("spine.license.feature_flags")

#: How long to trust a cached ``quota_remaining`` answer before re-reading
#: ``spine_license.quota_usage``. Quotas are billing — not security —
#: so a 60s staleness window is the explicit policy.
CACHE_TTL_SECONDS: int = int(
    os.environ.get("SPINE_LICENSE_QUOTA_CACHE_TTL_SECONDS", "60"),
)

#: Process-wide pool reference set by the Hub bootstrap so the cache
#: refresher can hit Postgres without threading the pool through every
#: caller. Tests install a mock pool here.
_POOL: Any = None


def set_pool(pool: Any) -> None:
    """Install the asyncpg pool used by :func:`quota_remaining`'s refresher."""
    global _POOL
    _POOL = pool


# ---------------------------------------------------------------------------
# is_enabled — pure read of the cached active bundle
# ---------------------------------------------------------------------------


def _known_flags() -> set[str]:
    """Lazy import to avoid a startup cycle with the middleware module."""
    from shared.api.middleware.feature_flag import KNOWN_FEATURE_FLAGS
    return set(KNOWN_FEATURE_FLAGS)


def _active_or_none() -> Optional[ActiveBundle]:
    """Return active bundle if signature still valid + not expired; else None."""
    bundle = get_active_bundle()
    if bundle is None:
        return None
    if not bundle.is_currently_valid():
        return None
    return bundle


def is_enabled(flag: str) -> bool:
    """Return True iff ``flag`` is enabled on the current license bundle.

    Raises ``KeyError`` for any flag not in
    ``shared.api.middleware.feature_flag.KNOWN_FEATURE_FLAGS`` so typos at
    a call site crash loudly. Fail-closed semantics: if no bundle has been
    loaded yet (bootstrap not complete) OR the bundle has been invalidated
    by a failed periodic re-verify OR the bundle has expired, every gate
    returns False.

    The one exception is ``license_inspector`` — the gate that protects
    the upgrade UI itself. Without that exception the customer couldn't
    reach the screen that explains why their licence is broken.
    """
    if flag not in _known_flags():
        raise KeyError(
            f"Unknown feature flag {flag!r}; add it to "
            "shared.api.middleware.feature_flag.KNOWN_FEATURE_FLAGS",
        )
    bundle = _active_or_none()
    if bundle is None:
        return flag == "license_inspector"
    for row in bundle.payload.feature_flags:
        if row.flag_name == flag:
            return bool(row.enabled)
    return flag == "license_inspector"


# ---------------------------------------------------------------------------
# quota_remaining — bundle quota minus persisted usage
# ---------------------------------------------------------------------------


_QUOTA_CACHE: dict[str, tuple[float, Optional[int]]] = {}


def invalidate_cache() -> None:
    """Drop the quota cache; the Hub admin UI calls this after a bundle change."""
    _QUOTA_CACHE.clear()


def _quota_for_flag(flag: str) -> Optional[int]:
    """Return the bundle-declared quota ceiling for ``flag`` (None = unlimited)."""
    bundle = _active_or_none()
    if bundle is None:
        return 0  # fail-closed: no bundle ⇒ no quota
    for row in bundle.payload.feature_flags:
        if row.flag_name == flag:
            return row.quota_value
    return 0


async def _read_used_value(flag: str) -> int:
    """Async DB read: SUM(used_value) over the active billing period.

    The "active billing period" is the row in ``spine_license.quota_usage``
    whose ``[period_start, period_end)`` covers ``now()``. If no such row
    exists yet the usage is 0 (the ledger writer will create it on first
    increment).
    """
    if _POOL is None:
        return 0
    now = datetime.now(timezone.utc)
    async with _POOL.acquire() as conn:
        val = await conn.fetchval(
            "SELECT COALESCE(SUM(used_value), 0) FROM spine_license.quota_usage "
            "WHERE flag_name = $1 AND period_start <= $2 AND period_end > $2;",
            flag, now,
        )
    return int(val or 0)


async def quota_remaining(flag: str) -> Optional[int]:
    """Return units remaining for ``flag`` in the active billing period.

    * ``None`` — the flag carries no quota (unlimited).
    * ``0``   — the flag is exhausted (or no bundle is loaded).
    * ``N``   — N units remain.

    The caller is responsible for honouring the return value (this
    function does not by itself block calls; that's the gate's job).
    Result is cached for ``CACHE_TTL_SECONDS`` so the hot path doesn't
    hit Postgres on every call.
    """
    if flag not in _known_flags():
        raise KeyError(
            f"Unknown feature flag {flag!r}; add it to KNOWN_FEATURE_FLAGS",
        )
    now = time.time()
    cached = _QUOTA_CACHE.get(flag)
    if cached is not None and (now - cached[0]) < CACHE_TTL_SECONDS:
        return cached[1]

    ceiling = _quota_for_flag(flag)
    if ceiling is None:
        _QUOTA_CACHE[flag] = (now, None)
        return None
    try:
        used = await _read_used_value(flag)
    except Exception as exc:  # noqa: BLE001 — fail-closed on DB hiccup
        logger.warning("quota_read_failed",
                       extra={"flag": flag, "err": str(exc)})
        return 0
    remaining = max(0, ceiling - used)
    _QUOTA_CACHE[flag] = (now, remaining)
    return remaining


# ---------------------------------------------------------------------------
# Diagnostics — used by MCP tools + admin UI
# ---------------------------------------------------------------------------


def status_snapshot() -> dict[str, Any]:
    """Return a dict describing the in-process licence state.

    Safe to surface in /api/v2/license; never includes signature bytes.
    """
    bundle = get_active_bundle()
    if bundle is None:
        return {
            "loaded": False, "signature_ok": False, "tier": None,
            "bundle_id": None, "customer": None, "expires_at": None,
            "flags": [],
        }
    return {
        "loaded": True,
        "signature_ok": bool(bundle.signature_ok),
        "tier": bundle.payload.tier,
        "bundle_id": bundle.payload.bundle_id,
        "customer": bundle.payload.customer,
        "issued_at": bundle.payload.issued_at.isoformat(),
        "expires_at": (
            bundle.payload.expires_at.isoformat()
            if bundle.payload.expires_at else None
        ),
        "last_verified_at": bundle.last_verified_at.isoformat(),
        "last_error": bundle.last_error,
        "flags": [
            {
                "flag_name": r.flag_name, "enabled": r.enabled,
                "quota_value": r.quota_value, "quota_unit": r.quota_unit,
            }
            for r in bundle.payload.feature_flags
        ],
    }


__all__ = [
    "CACHE_TTL_SECONDS",
    "invalidate_cache",
    "is_enabled",
    "quota_remaining",
    "set_pool",
    "status_snapshot",
]
