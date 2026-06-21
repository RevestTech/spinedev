"""
Expanded unit tests for Redis-backed rate limiting middleware.

Tests:
  - Per-minute rate limit bucket logic
  - Per-hour rate limit bucket logic
  - Redis interaction (incr, expire)
  - Rate limit headers in response
  - API key vs IP identification
  - Health and session-probe endpoint bypass
  - Redis unavailable scenarios
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from tron.api.middleware.rate_limit import RateLimitMiddleware
from tron.api.config import settings


class TestRateLimitMiddlewareBypass:
    """Tests for paths that skip Redis-backed rate limiting."""

    async def test_health_endpoint_bypassed(self):
        """Health endpoint skips rate limiting."""
        middleware = RateLimitMiddleware(MagicMock())
        request = MagicMock(spec=Request)
        request.url.path = "/health"
        
        call_next = AsyncMock(return_value=Response(status_code=200))
        
        result = await middleware.dispatch(request, call_next)
        
        assert result.status_code == 200
        call_next.assert_called_once()

    async def test_admin_me_endpoint_bypassed(self):
        """GET /api/admin/me skips rate limiting (session probe)."""
        middleware = RateLimitMiddleware(MagicMock())
        request = MagicMock(spec=Request)
        request.url.path = "/api/admin/me"

        call_next = AsyncMock(return_value=Response(status_code=200))

        result = await middleware.dispatch(request, call_next)

        assert result.status_code == 200
        call_next.assert_called_once()

    async def test_ready_endpoint_bypassed(self):
        """Ready endpoint skips rate limiting."""
        middleware = RateLimitMiddleware(MagicMock())
        request = MagicMock(spec=Request)
        request.url.path = "/ready"
        
        call_next = AsyncMock(return_value=Response(status_code=200))
        
        result = await middleware.dispatch(request, call_next)
        
        assert result.status_code == 200
        call_next.assert_called_once()

    async def test_other_paths_not_bypassed(self):
        """Non-health paths are rate-limited."""
        middleware = RateLimitMiddleware(MagicMock())
        request = MagicMock(spec=Request)
        request.url.path = "/api/audit"
        request.headers.get = MagicMock(return_value=None)  # No API key
        request.client = MagicMock(host="192.168.1.1")
        
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock(return_value=True)
        
        with patch("tron.api.middleware.rate_limit.get_redis", return_value=mock_redis):
            call_next = AsyncMock(return_value=Response(status_code=200))
            result = await middleware.dispatch(request, call_next)
        
        assert result.status_code == 200
        assert mock_redis.incr.called


class TestRateLimitRedisUnavailable:
    """Tests for behavior when Redis is unavailable."""

    async def test_redis_not_initialized_allows_request(self):
        """Request allowed through if Redis not initialized."""
        middleware = RateLimitMiddleware(MagicMock())
        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        
        call_next = AsyncMock(return_value=Response(status_code=200))
        
        with patch("tron.api.middleware.rate_limit.get_redis", side_effect=RuntimeError("not initialized")):
            result = await middleware.dispatch(request, call_next)
        
        assert result.status_code == 200
        call_next.assert_called_once()

    async def test_redis_connection_error_allows_request(self):
        """Request allowed through on Redis connection error."""
        middleware = RateLimitMiddleware(MagicMock())
        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        
        call_next = AsyncMock(return_value=Response(status_code=200))
        
        with patch("tron.api.middleware.rate_limit.get_redis", side_effect=RuntimeError("connection failed")):
            result = await middleware.dispatch(request, call_next)
        
        assert result.status_code == 200


class TestRateLimitPerMinute:
    """Tests for per-minute rate limiting."""

    async def test_per_minute_limit_exceeded_raises_429(self):
        """Exceeding per-minute limit raises 429."""
        middleware = RateLimitMiddleware(MagicMock())
        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        request.headers.get = MagicMock(return_value="api-key-123")
        request.client = MagicMock(host="192.168.1.1")
        
        mock_redis = AsyncMock()
        # Simulate exceeding per-minute limit
        mock_redis.incr = AsyncMock(return_value=settings.rate_limit_per_minute + 1)
        mock_redis.expire = AsyncMock(return_value=True)
        
        with patch("tron.api.middleware.rate_limit.get_redis", return_value=mock_redis):
            call_next = AsyncMock()
            
            with pytest.raises(HTTPException) as exc_info:
                await middleware.dispatch(request, call_next)
        
        assert exc_info.value.status_code == 429
        assert "minute" in exc_info.value.detail.lower()

    async def test_per_minute_limit_retry_after_header(self):
        """429 response includes Retry-After header for per-minute limit."""
        middleware = RateLimitMiddleware(MagicMock())
        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        request.headers.get = MagicMock(return_value="api-key-123")
        request.client = MagicMock(host="192.168.1.1")
        
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=settings.rate_limit_per_minute + 1)
        mock_redis.expire = AsyncMock(return_value=True)
        
        with patch("tron.api.middleware.rate_limit.get_redis", return_value=mock_redis):
            call_next = AsyncMock()
            
            with pytest.raises(HTTPException) as exc_info:
                await middleware.dispatch(request, call_next)
        
        assert exc_info.value.headers["Retry-After"] == "60"

    async def test_per_minute_bucket_key_format(self):
        """Per-minute bucket key includes API key hash."""
        middleware = RateLimitMiddleware(MagicMock())
        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        request.headers.get = MagicMock(return_value="api-key-123456789abcdef")
        request.client = MagicMock(host="192.168.1.1")
        
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock(return_value=True)
        
        with patch("tron.api.middleware.rate_limit.get_redis", return_value=mock_redis):
            call_next = AsyncMock(return_value=Response(status_code=200))
            await middleware.dispatch(request, call_next)
        
        # Verify the key format used
        incr_calls = mock_redis.incr.call_args_list
        assert len(incr_calls) >= 1
        minute_key = incr_calls[0][0][0]
        assert "ratelimit:key:" in minute_key
        assert "min:" in minute_key

    async def test_per_minute_expires_after_120_seconds(self):
        """Per-minute bucket TTL set to 120 seconds."""
        middleware = RateLimitMiddleware(MagicMock())
        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        request.headers.get = MagicMock(return_value="api-key-123")
        request.client = MagicMock(host="192.168.1.1")
        
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock(return_value=True)
        
        with patch("tron.api.middleware.rate_limit.get_redis", return_value=mock_redis):
            call_next = AsyncMock(return_value=Response(status_code=200))
            await middleware.dispatch(request, call_next)
        
        # Check expire calls
        expire_calls = mock_redis.expire.call_args_list
        minute_expire = expire_calls[0]
        assert minute_expire[0][1] == 120  # 120 second TTL


class TestRateLimitPerHour:
    """Tests for per-hour rate limiting."""

    async def test_per_hour_limit_exceeded_raises_429(self):
        """Exceeding per-hour limit raises 429."""
        middleware = RateLimitMiddleware(MagicMock())
        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        request.headers.get = MagicMock(return_value="api-key-123")
        request.client = MagicMock(host="192.168.1.1")
        
        mock_redis = AsyncMock()
        # First call (per-minute) succeeds, second (per-hour) exceeds
        mock_redis.incr = AsyncMock(side_effect=[1, settings.rate_limit_per_hour + 1])
        mock_redis.expire = AsyncMock(return_value=True)
        
        with patch("tron.api.middleware.rate_limit.get_redis", return_value=mock_redis):
            call_next = AsyncMock()
            
            with pytest.raises(HTTPException) as exc_info:
                await middleware.dispatch(request, call_next)
        
        assert exc_info.value.status_code == 429
        assert "hour" in exc_info.value.detail.lower()

    async def test_per_hour_limit_retry_after_header(self):
        """429 response includes Retry-After header for per-hour limit."""
        middleware = RateLimitMiddleware(MagicMock())
        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        request.headers.get = MagicMock(return_value="api-key-123")
        request.client = MagicMock(host="192.168.1.1")
        
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(side_effect=[1, settings.rate_limit_per_hour + 1])
        mock_redis.expire = AsyncMock(return_value=True)
        
        with patch("tron.api.middleware.rate_limit.get_redis", return_value=mock_redis):
            call_next = AsyncMock()
            
            with pytest.raises(HTTPException) as exc_info:
                await middleware.dispatch(request, call_next)
        
        assert exc_info.value.headers["Retry-After"] == "3600"

    async def test_per_hour_bucket_key_format(self):
        """Per-hour bucket key includes API key hash."""
        middleware = RateLimitMiddleware(MagicMock())
        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        request.headers.get = MagicMock(return_value="api-key-123456789abcdef")
        request.client = MagicMock(host="192.168.1.1")
        
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock(return_value=True)
        
        with patch("tron.api.middleware.rate_limit.get_redis", return_value=mock_redis):
            call_next = AsyncMock(return_value=Response(status_code=200))
            await middleware.dispatch(request, call_next)
        
        # Verify the key format
        incr_calls = mock_redis.incr.call_args_list
        assert len(incr_calls) >= 2
        hour_key = incr_calls[1][0][0]
        assert "ratelimit:key:" in hour_key
        assert "hr:" in hour_key

    async def test_per_hour_expires_after_7200_seconds(self):
        """Per-hour bucket TTL set to 7200 seconds."""
        middleware = RateLimitMiddleware(MagicMock())
        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        request.headers.get = MagicMock(return_value="api-key-123")
        request.client = MagicMock(host="192.168.1.1")
        
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock(return_value=True)
        
        with patch("tron.api.middleware.rate_limit.get_redis", return_value=mock_redis):
            call_next = AsyncMock(return_value=Response(status_code=200))
            await middleware.dispatch(request, call_next)
        
        # Check expire calls
        expire_calls = mock_redis.expire.call_args_list
        hour_expire = expire_calls[1]
        assert hour_expire[0][1] == 7200  # 7200 second TTL


class TestRateLimitIdentification:
    """Tests for API key vs IP-based identification."""

    async def test_identified_by_api_key_when_present(self):
        """Requests with API key identified by key, not IP."""
        middleware = RateLimitMiddleware(MagicMock())
        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        request.headers.get = MagicMock(return_value="my-api-key-123")
        request.client = MagicMock(host="192.168.1.100")
        
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock(return_value=True)
        
        with patch("tron.api.middleware.rate_limit.get_redis", return_value=mock_redis):
            call_next = AsyncMock(return_value=Response(status_code=200))
            await middleware.dispatch(request, call_next)
        
        # Check that bucket uses API key, not IP
        minute_key = mock_redis.incr.call_args_list[0][0][0]
        assert "ratelimit:key:" in minute_key
        assert "192.168.1.100" not in minute_key

    async def test_identified_by_ip_when_no_key(self):
        """Requests without API key identified by IP."""
        middleware = RateLimitMiddleware(MagicMock())
        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        request.headers.get = MagicMock(return_value=None)  # No API key
        request.client = MagicMock(host="203.0.113.42")
        
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock(return_value=True)
        
        with patch("tron.api.middleware.rate_limit.get_redis", return_value=mock_redis):
            call_next = AsyncMock(return_value=Response(status_code=200))
            await middleware.dispatch(request, call_next)
        
        # Check that bucket uses IP
        minute_key = mock_redis.incr.call_args_list[0][0][0]
        assert "ratelimit:ip:" in minute_key
        assert "203.0.113.42" in minute_key

    async def test_api_key_truncated_to_16_chars(self):
        """API key truncated to first 16 chars in bucket identifier."""
        middleware = RateLimitMiddleware(MagicMock())
        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        long_api_key = "sk-proj-1234567890abcdefghijklmnop"
        request.headers.get = MagicMock(return_value=long_api_key)
        request.client = MagicMock(host="192.168.1.1")
        
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock(return_value=True)
        
        with patch("tron.api.middleware.rate_limit.get_redis", return_value=mock_redis):
            call_next = AsyncMock(return_value=Response(status_code=200))
            await middleware.dispatch(request, call_next)
        
        # Verify truncation
        minute_key = mock_redis.incr.call_args_list[0][0][0]
        assert long_api_key[:16] in minute_key

    async def test_unknown_client_host_fallback(self):
        """Unknown client IP falls back to 'unknown'."""
        middleware = RateLimitMiddleware(MagicMock())
        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        request.headers.get = MagicMock(return_value=None)
        request.client = None  # No client info
        
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock(return_value=True)
        
        with patch("tron.api.middleware.rate_limit.get_redis", return_value=mock_redis):
            call_next = AsyncMock(return_value=Response(status_code=200))
            await middleware.dispatch(request, call_next)
        
        # Check fallback
        minute_key = mock_redis.incr.call_args_list[0][0][0]
        assert "unknown" in minute_key


class TestRateLimitResponseHeaders:
    """Tests for rate limit headers in response."""

    async def test_x_ratelimit_headers_added_to_response(self):
        """Rate limit headers added to successful response."""
        middleware = RateLimitMiddleware(MagicMock())
        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        request.headers.get = MagicMock(return_value="api-key-123")
        request.client = MagicMock(host="192.168.1.1")
        
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(side_effect=[10, 100])  # 10 this minute, 100 this hour
        mock_redis.expire = AsyncMock(return_value=True)
        
        response = Response(status_code=200)
        call_next = AsyncMock(return_value=response)
        
        with patch("tron.api.middleware.rate_limit.get_redis", return_value=mock_redis):
            result = await middleware.dispatch(request, call_next)
        
        assert "X-RateLimit-Limit-Minute" in result.headers
        assert "X-RateLimit-Remaining-Minute" in result.headers
        assert "X-RateLimit-Limit-Hour" in result.headers
        assert "X-RateLimit-Remaining-Hour" in result.headers

    async def test_remaining_count_calculation(self):
        """Remaining count calculated correctly."""
        middleware = RateLimitMiddleware(MagicMock())
        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        request.headers.get = MagicMock(return_value="api-key-123")
        request.client = MagicMock(host="192.168.1.1")
        
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(side_effect=[25, 200])
        mock_redis.expire = AsyncMock(return_value=True)
        
        response = Response(status_code=200)
        call_next = AsyncMock(return_value=response)
        
        with patch("tron.api.middleware.rate_limit.get_redis", return_value=mock_redis):
            result = await middleware.dispatch(request, call_next)
        
        # Remaining should be limit - count
        remaining_minute = int(result.headers["X-RateLimit-Remaining-Minute"])
        remaining_hour = int(result.headers["X-RateLimit-Remaining-Hour"])
        
        assert remaining_minute == settings.rate_limit_per_minute - 25
        assert remaining_hour == settings.rate_limit_per_hour - 200

    async def test_remaining_count_never_negative(self):
        """Remaining count clamped at zero minimum."""
        middleware = RateLimitMiddleware(MagicMock())
        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        request.headers.get = MagicMock(return_value="api-key-123")
        request.client = MagicMock(host="192.168.1.1")
        
        mock_redis = AsyncMock()
        # Count exceeds limit (shouldn't reach this far, but test anyway)
        mock_redis.incr = AsyncMock(side_effect=[200, 2000])
        mock_redis.expire = AsyncMock(return_value=True)
        
        call_next = AsyncMock()
        
        with patch("tron.api.middleware.rate_limit.get_redis", return_value=mock_redis):
            with pytest.raises(HTTPException):
                await middleware.dispatch(request, call_next)


class TestRateLimitBucketWindows:
    """Tests for bucket window calculations."""

    async def test_different_minute_buckets_for_different_times(self):
        """Different minute windows have different bucket keys."""
        middleware = RateLimitMiddleware(MagicMock())
        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        request.headers.get = MagicMock(return_value="api-key-123")
        request.client = MagicMock(host="192.168.1.1")
        
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock(return_value=True)
        
        with patch("tron.api.middleware.rate_limit.get_redis", return_value=mock_redis):
            with patch("time.time", return_value=1000):
                call_next = AsyncMock(return_value=Response(status_code=200))
                await middleware.dispatch(request, call_next)
        
        first_minute_key = mock_redis.incr.call_args_list[0][0][0]
        
        # Simulate different time
        mock_redis.reset_mock()
        
        with patch("tron.api.middleware.rate_limit.get_redis", return_value=mock_redis):
            with patch("time.time", return_value=1100):  # Different minute
                call_next = AsyncMock(return_value=Response(status_code=200))
                await middleware.dispatch(request, call_next)
        
        second_minute_key = mock_redis.incr.call_args_list[0][0][0]
        assert first_minute_key != second_minute_key

    async def test_same_hour_bucket_for_different_minutes(self):
        """Same hour window uses same bucket for different minutes."""
        middleware = RateLimitMiddleware(MagicMock())
        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        request.headers.get = MagicMock(return_value="api-key-123")
        request.client = MagicMock(host="192.168.1.1")
        
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock(return_value=True)
        
        with patch("tron.api.middleware.rate_limit.get_redis", return_value=mock_redis):
            with patch("time.time", return_value=3600):  # 1 hour
                call_next = AsyncMock(return_value=Response(status_code=200))
                await middleware.dispatch(request, call_next)
        
        first_hour_key = mock_redis.incr.call_args_list[1][0][0]
        
        # Simulate 30 minutes later (same hour)
        mock_redis.reset_mock()
        
        with patch("tron.api.middleware.rate_limit.get_redis", return_value=mock_redis):
            with patch("time.time", return_value=3600 + 1800):  # 30 mins later
                call_next = AsyncMock(return_value=Response(status_code=200))
                await middleware.dispatch(request, call_next)
        
        second_hour_key = mock_redis.incr.call_args_list[1][0][0]
        assert first_hour_key == second_hour_key
