"""
Redis-backed rate limiting middleware.

Uses a sliding window counter per API key.
Limits configured via Settings (non-secret config).
"""

from __future__ import annotations

import logging
import time

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from tron.api.config import settings
from tron.infra.redis.client import get_redis

logger = logging.getLogger(__name__)

# Cheap session probes (cookie auth has no X-API-Key; SPA may call often). Exempt from the shared IP bucket.
_RATE_LIMIT_BYPASS_PATHS: frozenset[str] = frozenset(
    {
        "/health",
        "/ready",
        "/api/admin/me",
    }
)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Sliding window rate limiter backed by Redis.

    Applies per API key (from X-API-Key header) or per IP if no key.
    Two windows: per-minute and per-hour.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.url.path in _RATE_LIMIT_BYPASS_PATHS:
            return await call_next(request)

        try:
            redis = get_redis()
        except RuntimeError:
            # Redis not initialized — let request through (startup race)
            return await call_next(request)

        # Identify caller: API key or IP
        api_key = request.headers.get("X-API-Key")
        if api_key:
            identifier = f"ratelimit:key:{api_key[:16]}"
        else:
            host = request.client.host if request.client else "unknown"
            identifier = f"ratelimit:ip:{host}"

        now = time.time()

        # Per-minute check
        minute_key = f"{identifier}:min:{int(now // 60)}"
        minute_count = await redis.incr(minute_key)
        if minute_count == 1:
            await redis.expire(minute_key, 120)  # TTL: 2 minutes for safety

        if minute_count > settings.rate_limit_per_minute:
            logger.warning("Rate limit exceeded (per-minute): %s", identifier)
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Try again in a minute.",
                headers={"Retry-After": "60"},
            )

        # Per-hour check
        hour_key = f"{identifier}:hr:{int(now // 3600)}"
        hour_count = await redis.incr(hour_key)
        if hour_count == 1:
            await redis.expire(hour_key, 7200)  # TTL: 2 hours for safety

        if hour_count > settings.rate_limit_per_hour:
            logger.warning("Rate limit exceeded (per-hour): %s", identifier)
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded per hour. Try again later.",
                headers={"Retry-After": "3600"},
            )

        # Add rate limit headers to response
        response = await call_next(request)
        response.headers["X-RateLimit-Limit-Minute"] = str(settings.rate_limit_per_minute)
        response.headers["X-RateLimit-Remaining-Minute"] = str(
            max(0, settings.rate_limit_per_minute - minute_count)
        )
        response.headers["X-RateLimit-Limit-Hour"] = str(settings.rate_limit_per_hour)
        response.headers["X-RateLimit-Remaining-Hour"] = str(
            max(0, settings.rate_limit_per_hour - hour_count)
        )

        return response
