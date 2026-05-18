"""Per-org rate-limiting middleware (V3 Wave 6 Stream J, #30).

Algorithm: **per-(org, route) token bucket** filled from the
``spine_license.feature_flag`` row whose ``flag_name`` matches the
mapped flag for the route. Concretely::

    capacity   = quota_value                                  (bucket size)
    refill     = quota_value tokens per refill_window         (refill rate)

The refill window is derived from ``quota_unit`` (one of
``shared.schemas.license.QuotaUnit``):

* ``runs_per_day``    -> 86400 s
* ``tokens_per_day``  -> 86400 s
* ``agents_per_month``-> 2_592_000 s (30 days, deliberate flat-line)
* ``projects``        -> not rate-limited (semantic cap; enforced elsewhere)
* ``seats``           -> not rate-limited (semantic cap; enforced elsewhere)

A request consumes one token. When the bucket would go negative, the
middleware returns ``429 Too Many Requests`` with ``Retry-After`` set to
the integer number of seconds until the next token refills, AND a
structured JSON body with ``error_code='rate_limited'`` + the
``feature_flag`` + ``quota_value`` + ``quota_unit`` so the SPA can show
the user "you have hit your quota; upgrade or wait Ns".

Where the quotas come from (per #9 — no env-var secrets):

* Production: ``shared.secrets.get_secret('spine/postgres/dsn')`` ->
  asyncpg pool initialised by ``shared.api.dependencies.init_db_pool``
  (already on disk; we just reuse the pool).
* Tests: ``set_quota_provider`` lets the test inject a static dict
  without touching DB.

Hot-path constraints:

* The bucket state lives **in-process** in an ``asyncio.Lock``-guarded
  dict — Wave 6 ships single-Hub semantics; Wave 6.5+ moves the bucket
  to Redis for multi-Hub fan-out. The contract here is forward-compat
  with that move (every read/write happens through ``_BucketStore``).
* The quota_value lookup is cached for ``QUOTA_CACHE_TTL_SECONDS`` so
  the hot path is not a Postgres round-trip on every request.
* Failures to read the quota table FAIL OPEN (log + allow) — running
  out of database in the middle of the night is bad, but locking every
  user out because of it is worse. We surface the failure in metrics
  + audit so on-call sees it.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Final, Optional

try:  # pragma: no cover - guarded for py_compile
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response
    from starlette.types import ASGIApp
except Exception:  # pragma: no cover

    class BaseHTTPMiddleware:  # type: ignore[no-redef]
        def __init__(self, app: object) -> None:
            self.app = app

    Request = object  # type: ignore[assignment,misc]
    JSONResponse = object  # type: ignore[assignment,misc]
    Response = object  # type: ignore[assignment,misc]
    ASGIApp = object  # type: ignore[assignment,misc]


logger = logging.getLogger("spine.api.rate_limit")


# ---------------------------------------------------------------------------
# Window mapping (#23 QuotaUnit -> seconds)
# ---------------------------------------------------------------------------

#: Wall-clock seconds per refill window, keyed by QuotaUnit. Units not
#: in this dict are NOT rate-limited (e.g. ``projects`` / ``seats`` are
#: semantic ceilings, not rates).
QUOTA_UNIT_WINDOWS_SECONDS: Final[dict[str, int]] = {
    "runs_per_day": 86_400,
    "tokens_per_day": 86_400,
    "agents_per_month": 30 * 86_400,
}

#: How long we cache a per-org quota row before re-reading the DB.
#: Short enough that a tier upgrade takes effect within a minute; long
#: enough that the hot path doesn't hammer Postgres.
QUOTA_CACHE_TTL_SECONDS: Final[float] = 30.0

#: Header the middleware reads to identify the org. Federation deployments
#: tunnel this through the auth layer (Keycloak claim -> request.state).
#: Fall back to a literal ``"local"`` so single-tenant Hubs work out of
#: the box without bundle propagation.
ORG_ID_HEADER: Final[str] = "X-Spine-Org-ID"
DEFAULT_ORG_ID: Final[str] = "local"


# ---------------------------------------------------------------------------
# Quota providers — pluggable so tests don't need a live Postgres
# ---------------------------------------------------------------------------


QuotaTuple = tuple[Optional[int], Optional[str]]
"""(quota_value, quota_unit) — both may be None (unlimited / no-rate)."""


QuotaProvider = Callable[[str, str], Awaitable[QuotaTuple]]
"""``async (org_id, flag_name) -> (quota_value, quota_unit)`` lookup."""


async def _default_quota_provider(org_id: str, flag_name: str) -> QuotaTuple:
    """Default provider: read ``spine_license.feature_flag`` via the pool.

    Uses the SAME asyncpg pool the rest of the Hub uses (per #9 the DSN
    came from vault) so we never read DSN VALUES in this module. Fails
    open with a warning if the pool is uninit (e.g. tests, Hub still
    booting) — the caller treats ``(None, None)`` as "no rate limit".
    """
    try:
        from shared.api.dependencies import get_db_pool_raw  # noqa: PLC0415

        pool = get_db_pool_raw()
    except Exception as exc:  # noqa: BLE001
        logger.debug("quota_pool_unavailable", extra={"error": str(exc)})
        return (None, None)
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                # We don't yet have org_id on spine_license.feature_flag
                # (Wave 6.5 adds per-org bundles); for now the active
                # bundle is the org's bundle by definition (single-tenant
                # Hub assumption). The org_id arg is plumbed through
                # so the Wave-6.5 query change is a one-liner.
                "SELECT quota_value, quota_unit "
                "FROM spine_license.feature_flag "
                "WHERE flag_name = $1 AND enabled = true "
                "ORDER BY updated_at DESC NULLS LAST LIMIT 1;",
                flag_name,
            )
    except Exception as exc:  # noqa: BLE001 — fail open
        logger.warning(
            "quota_lookup_failed",
            extra={"org_id": org_id, "flag_name": flag_name, "error": str(exc)},
        )
        return (None, None)
    if row is None:
        return (None, None)
    return (
        int(row["quota_value"]) if row["quota_value"] is not None else None,
        str(row["quota_unit"]) if row["quota_unit"] is not None else None,
    )


_QUOTA_PROVIDER: QuotaProvider = _default_quota_provider


def set_quota_provider(provider: QuotaProvider | None) -> None:
    """Swap the quota lookup function (tests + Wave-6.5 Redis backend)."""
    global _QUOTA_PROVIDER
    _QUOTA_PROVIDER = provider or _default_quota_provider


def get_quota_provider() -> QuotaProvider:
    """Inspect the currently-installed provider (diagnostics + tests)."""
    return _QUOTA_PROVIDER


# ---------------------------------------------------------------------------
# Bucket store — in-process for Wave 6, Redis-shaped for future
# ---------------------------------------------------------------------------


@dataclass
class _Bucket:
    """One token bucket; mutated in place under ``_BucketStore``'s lock.

    Tokens are stored as a float so partial refills work without integer
    rounding drift over long periods. We round DOWN on the spend check
    (you can't spend half a token), but track the surplus precisely.
    """

    capacity: float
    tokens: float
    refill_per_second: float
    last_refill_ts: float
    quota_value: int = 0
    quota_unit: str = ""

    def refill(self, now: float) -> None:
        """Add accumulated tokens since the last touch, clamped at capacity."""
        if now <= self.last_refill_ts:
            return
        delta = now - self.last_refill_ts
        self.tokens = min(self.capacity, self.tokens + delta * self.refill_per_second)
        self.last_refill_ts = now

    def seconds_until_one_token(self, now: float) -> float:
        """How many seconds until the bucket holds >= 1 token (after refill).

        Used to populate ``Retry-After``. Always >= 0; equals 0 if the
        bucket already has >= 1 token.
        """
        self.refill(now)
        if self.tokens >= 1.0:
            return 0.0
        if self.refill_per_second <= 0.0:
            return float("inf")
        return (1.0 - self.tokens) / self.refill_per_second


@dataclass
class _QuotaCacheEntry:
    """Cached (quota_value, quota_unit) pair with expiry."""

    quota_value: Optional[int]
    quota_unit: Optional[str]
    expires_at: float


@dataclass
class _BucketStore:
    """Process-local bucket + quota cache. Threadsafe via single asyncio.Lock.

    Keys are ``(org_id, flag_name)`` so two routes that map to the same
    flag share one bucket (correct quota semantics — quota is on the
    capability, not on the URL path).
    """

    _buckets: dict[tuple[str, str], _Bucket] = field(default_factory=dict)
    _quota_cache: dict[tuple[str, str], _QuotaCacheEntry] = field(
        default_factory=dict
    )
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def consume(
        self,
        *,
        org_id: str,
        flag_name: str,
        provider: QuotaProvider,
        now_fn: Callable[[], float] = time.monotonic,
    ) -> tuple[bool, Optional[_Bucket], float]:
        """Try to spend one token.

        Returns ``(allowed, bucket, retry_after_seconds)``. ``bucket`` is
        ``None`` when the flag has no rate (quota_value is None or
        quota_unit is not in QUOTA_UNIT_WINDOWS_SECONDS) — in that case
        the request is always allowed and the middleware skips the
        rate-limit headers entirely.
        """
        async with self._lock:
            now = now_fn()
            cache_key = (org_id, flag_name)

            # 1. Resolve (and cache) the quota row.
            cached = self._quota_cache.get(cache_key)
            if cached is None or cached.expires_at <= now:
                qv, qu = await provider(org_id, flag_name)
                cached = _QuotaCacheEntry(
                    quota_value=qv,
                    quota_unit=qu,
                    expires_at=now + QUOTA_CACHE_TTL_SECONDS,
                )
                self._quota_cache[cache_key] = cached

            qv = cached.quota_value
            qu = cached.quota_unit
            if (
                qv is None
                or qv <= 0
                or qu is None
                or qu not in QUOTA_UNIT_WINDOWS_SECONDS
            ):
                # No rate limit applies (unlimited, disabled, or
                # non-rate-shaped quota like 'projects').
                return (True, None, 0.0)

            window = QUOTA_UNIT_WINDOWS_SECONDS[qu]
            refill_per_sec = float(qv) / float(window)

            # 2. Resolve (and lazily create) the bucket.
            bucket = self._buckets.get(cache_key)
            if bucket is None or bucket.capacity != float(qv):
                # First request OR quota changed -> reset bucket. Tier
                # upgrade refills fully so the user feels the change.
                bucket = _Bucket(
                    capacity=float(qv),
                    tokens=float(qv),
                    refill_per_second=refill_per_sec,
                    last_refill_ts=now,
                    quota_value=int(qv),
                    quota_unit=str(qu),
                )
                self._buckets[cache_key] = bucket
            else:
                # Existing bucket: refresh refill rate in case the
                # window shape changed (paranoid, cheap).
                bucket.refill_per_second = refill_per_sec

            # 3. Refill + try to spend.
            bucket.refill(now)
            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return (True, bucket, 0.0)

            retry_after = bucket.seconds_until_one_token(now)
            return (False, bucket, retry_after)

    def reset(self) -> None:
        """Drop every bucket + cache entry (test fixture seam)."""
        self._buckets.clear()
        self._quota_cache.clear()


_STORE: _BucketStore = _BucketStore()


def get_bucket_store() -> _BucketStore:
    """Process-wide bucket store accessor (mainly for tests + diagnostics)."""
    return _STORE


def reset_bucket_store() -> None:
    """Empty the bucket store — called by test teardowns."""
    _STORE.reset()


# ---------------------------------------------------------------------------
# Route -> feature-flag mapping
# ---------------------------------------------------------------------------


#: Map of URL path prefix to the licence flag that gates its quota. Order
#: matters: longest-prefix match wins so ``/api/v2/integrations/x/test``
#: routes to the integration flag, not a generic catch-all.
ROUTE_FLAG_MAP: Final[tuple[tuple[str, str], ...]] = (
    ("/api/v2/integrations/github", "integration_github"),
    ("/api/v2/integrations/linear", "integration_linear"),
    ("/api/v2/integrations/jira", "integration_jira"),
    ("/api/v2/integrations/vanta", "integration_vanta"),
    ("/api/v2/integrations/drata", "integration_drata"),
    ("/api/v2/federation", "federation"),
    ("/api/v2/role-chat", "remote_mcp"),
    ("/api/v2/decisions", "hub_admin"),
    # Default catch-all for any other /api/v2/* call: gate on the
    # generic 'quota_max_concurrent_runs' feature so the customer's
    # global Hub rate is respected. Listed LAST so explicit prefixes win.
    ("/api/v2/", "quota_max_concurrent_runs"),
)


def map_route_to_flag(path: str) -> Optional[str]:
    """Longest-prefix match from path -> feature-flag name."""
    best: tuple[int, Optional[str]] = (-1, None)
    for prefix, flag in ROUTE_FLAG_MAP:
        if path.startswith(prefix) and len(prefix) > best[0]:
            best = (len(prefix), flag)
    return best[1]


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-org token-bucket rate limiter on the public REST surface.

    Skip conditions (return early without consuming a token):

    * ``OPTIONS`` requests — CORS preflight is not a billed call.
    * Paths not in :data:`ROUTE_FLAG_MAP` — health/readiness/OpenAPI
      docs are operational + free.
    * No rate is configured for the resolved flag (``quota_value`` NULL
      or ``quota_unit`` not a rate-shaped unit).
    """

    #: Methods we never rate-limit. OPTIONS is preflight; HEAD is the
    #: GET twin (we let it count if the GET would, but it's rarely
    #: relevant on this surface).
    SKIP_METHODS: Final[frozenset[str]] = frozenset({"OPTIONS"})

    async def dispatch(
        self,
        request: "Request",
        call_next: Callable[["Request"], Awaitable["Response"]],
    ) -> "Response":  # type: ignore[override]
        if request.method in self.SKIP_METHODS:
            return await call_next(request)
        path = request.url.path
        flag = map_route_to_flag(path)
        if flag is None:
            return await call_next(request)

        org_id = (
            request.headers.get(ORG_ID_HEADER)
            or getattr(request.state, "org_id", None)
            or DEFAULT_ORG_ID
        )

        allowed, bucket, retry_after = await _STORE.consume(
            org_id=org_id,
            flag_name=flag,
            provider=_QUOTA_PROVIDER,
        )
        if not allowed:
            retry_secs = max(1, math.ceil(retry_after))
            logger.info(
                "rate_limited",
                extra={
                    "org_id": org_id,
                    "flag": flag,
                    "path": path,
                    "method": request.method,
                    "retry_after": retry_secs,
                },
            )
            body: dict[str, Any] = {
                "error_code": "rate_limited",
                "message": (
                    f"Quota exceeded for feature {flag!r}; "
                    f"retry in {retry_secs}s."
                ),
                "feature_flag": flag,
                "retry_after_seconds": retry_secs,
            }
            if bucket is not None:
                body["quota_value"] = bucket.quota_value
                body["quota_unit"] = bucket.quota_unit
            response = JSONResponse(body, status_code=429)
            response.headers["Retry-After"] = str(retry_secs)
            response.headers["X-Spine-Rate-Limit-Flag"] = flag
            return response

        response = await call_next(request)
        # Surface the remaining-budget header for observability — the
        # SPA renders a "X requests left" badge on the Hub admin pages.
        if bucket is not None:
            response.headers["X-Spine-Rate-Limit-Remaining"] = str(
                max(0, int(bucket.tokens))
            )
            response.headers["X-Spine-Rate-Limit-Capacity"] = str(
                int(bucket.capacity)
            )
            response.headers["X-Spine-Rate-Limit-Flag"] = flag
        return response


def install_rate_limit_middleware(app: "ASGIApp") -> "ASGIApp":
    """FastAPI helper: ``install_rate_limit_middleware(app)``."""
    try:
        app.add_middleware(RateLimitMiddleware)  # type: ignore[attr-defined]
    except AttributeError:  # pragma: no cover
        raise RuntimeError(
            "install_rate_limit_middleware requires a FastAPI/Starlette app",
        )
    return app


__all__ = [
    "DEFAULT_ORG_ID",
    "ORG_ID_HEADER",
    "QUOTA_CACHE_TTL_SECONDS",
    "QUOTA_UNIT_WINDOWS_SECONDS",
    "QuotaProvider",
    "QuotaTuple",
    "ROUTE_FLAG_MAP",
    "RateLimitMiddleware",
    "get_bucket_store",
    "get_quota_provider",
    "install_rate_limit_middleware",
    "map_route_to_flag",
    "reset_bucket_store",
    "set_quota_provider",
]
