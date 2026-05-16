"""
Integration tests for health endpoints.

Tests:
  - /health returns ok (no deps needed)
  - /ready returns status with DB + Redis checks
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestHealthEndpoint:

    async def test_health_returns_ok(self, api_client):
        """GET /health → 200 with status ok."""
        response = await api_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "tron-api"
        assert "uptime_seconds" in data


class TestReadyEndpoint:

    async def test_ready_when_all_ok(self, api_client):
        """GET /ready → 200 when DB and Redis are connected."""
        # Mock both DB engine and Redis
        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 1
        mock_conn.execute = AsyncMock(return_value=mock_result)
        mock_engine.connect = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_conn),
            __aexit__=AsyncMock(return_value=False),
        ))

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)

        with patch("tron.api.routes.health.get_engine", return_value=mock_engine), \
             patch("tron.api.routes.health.get_redis", return_value=mock_redis):
            response = await api_client.get("/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"

    async def test_ready_fails_when_db_down(self, api_client):
        """GET /ready → 503 when database is unreachable."""
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)

        with patch("tron.api.routes.health.get_engine", side_effect=RuntimeError("DB not initialized")), \
             patch("tron.api.routes.health.get_redis", return_value=mock_redis):
            response = await api_client.get("/ready")

        assert response.status_code == 503
