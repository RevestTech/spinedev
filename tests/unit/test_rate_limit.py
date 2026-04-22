"""
Unit tests for RateLimitMiddleware.

Tests:
  - Health and `/api/admin/me` bypass rate limiting
  - Per-minute rate limit exceeded → 429
  - Per-hour rate limit exceeded → 429
  - Rate limit headers present on responses
  - Identifier based on API key vs IP
  - Redis unavailable → request passes through
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient

from tron.api.middleware.rate_limit import RateLimitMiddleware


def _create_test_app() -> FastAPI:
    """Create a minimal FastAPI app with rate limit middleware.

    Note: HTTPException raised from BaseHTTPMiddleware gets caught by
    Starlette's ServerErrorMiddleware and returned as 500 in TestClient.
    We install an explicit handler so the 429 propagates correctly.
    """
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/test")
    async def test_endpoint():
        return {"data": "ok"}

    @app.get("/api/admin/me")
    async def admin_me():
        return {"ok": True}

    # Add the rate limit middleware AFTER routes so the exception handler
    # is in the right position in the middleware stack.
    app.add_middleware(RateLimitMiddleware)

    return app


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.incr = AsyncMock(return_value=1)
    r.expire = AsyncMock()
    return r


class TestHealthBypass:

    def test_health_skips_rate_limit(self):
        """Health endpoint bypasses rate limiting entirely."""
        app = _create_test_app()
        with patch("tron.api.middleware.rate_limit.get_redis", side_effect=RuntimeError("no redis")):
            client = TestClient(app)
            response = client.get("/health")
            assert response.status_code == 200

    def test_admin_me_skips_rate_limit(self):
        """Session probe bypasses rate limiting (no Redis / no counters)."""
        app = _create_test_app()
        with patch("tron.api.middleware.rate_limit.get_redis", side_effect=RuntimeError("no redis")):
            client = TestClient(app)
            response = client.get("/api/admin/me")
            assert response.status_code == 200


class TestRedisUnavailable:

    def test_redis_not_initialized_passes_through(self):
        """When Redis is not available, requests pass through."""
        app = _create_test_app()
        with patch("tron.api.middleware.rate_limit.get_redis", side_effect=RuntimeError("not init")):
            client = TestClient(app)
            response = client.get("/api/test")
            assert response.status_code == 200


class TestRateLimitHeaders:

    def test_response_includes_rate_limit_headers(self, mock_redis):
        """Successful requests include rate limit headers."""
        app = _create_test_app()
        with patch("tron.api.middleware.rate_limit.get_redis", return_value=mock_redis):
            client = TestClient(app)
            response = client.get("/api/test", headers={"X-API-Key": "test-key"})

        assert response.status_code == 200
        assert "X-RateLimit-Limit-Minute" in response.headers
        assert "X-RateLimit-Remaining-Minute" in response.headers
        assert "X-RateLimit-Limit-Hour" in response.headers
        assert "X-RateLimit-Remaining-Hour" in response.headers


class TestPerMinuteLimit:

    def test_exceeds_per_minute(self, mock_redis):
        """Exceeding per-minute limit raises HTTPException(429)."""
        app = _create_test_app()
        mock_redis.incr = AsyncMock(return_value=99999)
        with patch("tron.api.middleware.rate_limit.get_redis", return_value=mock_redis), \
             patch("tron.api.middleware.rate_limit.settings") as mock_settings:
            mock_settings.rate_limit_per_minute = 60
            mock_settings.rate_limit_per_hour = 1000

            # BaseHTTPMiddleware converts HTTPException to 500 in TestClient,
            # so we use raise_server_exceptions=True and catch it directly
            client = TestClient(app, raise_server_exceptions=True)
            with pytest.raises(HTTPException) as exc_info:
                client.get("/api/test", headers={"X-API-Key": "test-key"})

            assert exc_info.value.status_code == 429


class TestPerHourLimit:

    def test_exceeds_per_hour(self, mock_redis):
        """Exceeding per-hour limit raises HTTPException(429)."""
        app = _create_test_app()
        mock_redis.incr = AsyncMock(side_effect=[1, 99999])
        with patch("tron.api.middleware.rate_limit.get_redis", return_value=mock_redis), \
             patch("tron.api.middleware.rate_limit.settings") as mock_settings:
            mock_settings.rate_limit_per_minute = 60
            mock_settings.rate_limit_per_hour = 1000

            client = TestClient(app, raise_server_exceptions=True)
            with pytest.raises(HTTPException) as exc_info:
                client.get("/api/test", headers={"X-API-Key": "test-key"})

            assert exc_info.value.status_code == 429


class TestIdentifier:

    def test_api_key_based_identifier(self, mock_redis):
        """With X-API-Key, identifier uses the key prefix."""
        app = _create_test_app()
        calls = []
        original_incr = mock_redis.incr

        async def track_incr(key):
            calls.append(key)
            return 1

        mock_redis.incr = track_incr

        with patch("tron.api.middleware.rate_limit.get_redis", return_value=mock_redis):
            client = TestClient(app)
            client.get("/api/test", headers={"X-API-Key": "my-secret-api-key-12345"})

        # Should use key-based identifier
        assert any("ratelimit:key:" in c for c in calls)

    def test_ip_based_identifier_when_no_key(self, mock_redis):
        """Without X-API-Key, identifier uses IP."""
        app = _create_test_app()
        calls = []

        async def track_incr(key):
            calls.append(key)
            return 1

        mock_redis.incr = track_incr

        with patch("tron.api.middleware.rate_limit.get_redis", return_value=mock_redis):
            client = TestClient(app)
            client.get("/api/test")

        assert any("ratelimit:ip:" in c for c in calls)
