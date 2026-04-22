"""
Unit tests for health check endpoints.

Tests:
  - /health liveness probe
  - /ready readiness probe with database and Redis checks
  - Redis failure handling in readiness check
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestHealthEndpoint:
    """Test /health liveness probe."""

    async def test_health_returns_ok_status(self):
        """GET /health should return ok status."""
        from tron.api.routes.health import health

        result = await health()

        assert result["status"] == "ok"
        assert result["service"] == "tron-api"
        assert "uptime_seconds" in result


class TestReadyEndpoint:
    """Test /ready readiness probe."""

    async def test_ready_returns_200_when_all_ok(self):
        """GET /ready should return 200 when DB and Redis are OK."""
        from tron.api.routes.health import ready

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar = MagicMock(return_value=1)
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_engine = MagicMock()

        @asynccontextmanager
        async def fake_connect():
            yield mock_conn

        mock_engine.connect = fake_connect

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock()

        with patch("tron.api.routes.health.get_engine", return_value=mock_engine), \
             patch("tron.api.routes.health.get_redis", return_value=mock_redis):
            result = await ready()

        assert result.status_code == 200
        assert "ready" in result.body.decode()

    async def test_ready_returns_503_when_db_fails(self):
        """GET /ready should return 503 when database check fails."""
        from tron.api.routes.health import ready

        with patch("tron.api.routes.health.get_engine", side_effect=RuntimeError("DB down")), \
             patch("tron.api.routes.health.get_redis", return_value=AsyncMock()):
            result = await ready()

        assert result.status_code == 503

    async def test_ready_returns_503_when_redis_fails(self):
        """GET /ready should return 503 when Redis check fails."""
        from tron.api.routes.health import ready

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar = MagicMock(return_value=1)
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_engine = MagicMock()

        @asynccontextmanager
        async def fake_connect():
            yield mock_conn

        mock_engine.connect = fake_connect

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=RuntimeError("Redis down"))

        with patch("tron.api.routes.health.get_engine", return_value=mock_engine), \
             patch("tron.api.routes.health.get_redis", return_value=mock_redis):
            result = await ready()

        assert result.status_code == 503


class TestReadyChecks:
    """Test individual readiness check failures."""

    async def test_ready_checks_include_database_and_redis(self):
        """ready() should include checks for both database and redis."""
        from tron.api.routes.health import ready

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar = MagicMock(return_value=1)
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_engine = MagicMock()

        @asynccontextmanager
        async def fake_connect():
            yield mock_conn

        mock_engine.connect = fake_connect

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock()

        with patch("tron.api.routes.health.get_engine", return_value=mock_engine), \
             patch("tron.api.routes.health.get_redis", return_value=mock_redis):
            result = await ready()

        # Parse response to check the checks
        import json

        body = json.loads(result.body.decode())
        assert "database" in body["checks"]
        assert "redis" in body["checks"]
        assert body["checks"]["database"] == "ok"
        assert body["checks"]["redis"] == "ok"

    async def test_redis_readiness_check_failure(self):
        """When Redis ping fails, readiness check should mark Redis as error."""
        from tron.api.routes.health import ready

        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar = MagicMock(return_value=1)
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_engine = MagicMock()

        @asynccontextmanager
        async def fake_connect():
            yield mock_conn

        mock_engine.connect = fake_connect

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=RuntimeError("Redis unavailable"))

        with patch("tron.api.routes.health.get_engine", return_value=mock_engine), \
             patch("tron.api.routes.health.get_redis", return_value=mock_redis):
            result = await ready()

        assert result.status_code == 503

        import json

        body = json.loads(result.body.decode())
        assert "error" in body["checks"]["redis"]
