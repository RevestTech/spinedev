"""
Unit tests for Redis client module.

Tests:
  - get_redis raises when not initialized
  - get_redis returns pool after init
  - close_redis clears pool
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

import tron.infra.redis.client as redis_mod


class TestGetRedis:

    def test_raises_when_not_initialized(self):
        """get_redis raises RuntimeError if pool is None."""
        original = redis_mod._pool
        redis_mod._pool = None
        try:
            with pytest.raises(RuntimeError, match="not initialized"):
                redis_mod.get_redis()
        finally:
            redis_mod._pool = original

    def test_returns_pool_when_set(self):
        """get_redis returns the pool object."""
        original = redis_mod._pool
        fake_pool = AsyncMock()
        redis_mod._pool = fake_pool
        try:
            result = redis_mod.get_redis()
            assert result is fake_pool
        finally:
            redis_mod._pool = original


class TestCloseRedis:

    async def test_close_clears_pool(self):
        """close_redis calls aclose and clears the global."""
        original = redis_mod._pool
        fake_pool = AsyncMock()
        redis_mod._pool = fake_pool
        try:
            await redis_mod.close_redis()
            assert redis_mod._pool is None
            fake_pool.aclose.assert_called_once()
        finally:
            redis_mod._pool = original

    async def test_close_noop_when_none(self):
        """close_redis is safe when pool is None."""
        original = redis_mod._pool
        redis_mod._pool = None
        try:
            await redis_mod.close_redis()  # Should not raise
        finally:
            redis_mod._pool = original


# ── Init Redis Tests ───────────────────────────────────────────────


class TestInitRedis:
    """Test Redis connection pool initialization."""

    async def test_init_redis_creates_pool_with_defaults(self):
        """init_redis should create pool with correct default parameters."""
        original = redis_mod._pool
        try:
            redis_mod._pool = None

            with patch("redis.asyncio.from_url") as mock_from_url:
                mock_pool = AsyncMock()
                mock_pool.ping = AsyncMock()
                mock_from_url.return_value = mock_pool

                await redis_mod.init_redis("redis://localhost:6379")

                call_kwargs = mock_from_url.call_args[1]
                assert call_kwargs["max_connections"] == 50
                assert call_kwargs["decode_responses"] is True
                assert call_kwargs["socket_connect_timeout"] == 5
                assert call_kwargs["socket_timeout"] == 5
                assert call_kwargs["retry_on_timeout"] is True

        finally:
            redis_mod._pool = original

    async def test_init_redis_custom_pool_size(self):
        """init_redis should accept custom pool_size parameter."""
        original = redis_mod._pool
        try:
            redis_mod._pool = None

            with patch("redis.asyncio.from_url") as mock_from_url:
                mock_pool = AsyncMock()
                mock_pool.ping = AsyncMock()
                mock_from_url.return_value = mock_pool

                await redis_mod.init_redis(
                    "redis://localhost:6379",
                    pool_size=100,
                )

                call_kwargs = mock_from_url.call_args[1]
                assert call_kwargs["max_connections"] == 100

        finally:
            redis_mod._pool = original

    async def test_init_redis_pings_connection(self):
        """init_redis should verify connection with ping()."""
        original = redis_mod._pool
        try:
            redis_mod._pool = None

            with patch("redis.asyncio.from_url") as mock_from_url:
                mock_pool = AsyncMock()
                mock_pool.ping = AsyncMock()
                mock_from_url.return_value = mock_pool

                await redis_mod.init_redis("redis://localhost:6379")

                mock_pool.ping.assert_called_once()

        finally:
            redis_mod._pool = original
