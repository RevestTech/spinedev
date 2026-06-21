"""
Unit tests for application configuration.

Tests:
  - URL builders (database_url, redis_url)
  - Default values
  - temporal_enabled flag
"""

from __future__ import annotations


from tron.api.config import Settings


class TestSettings:

    def test_database_url(self):
        s = Settings()
        url = s.database_url("testpassword")
        assert "postgresql+asyncpg://" in url
        assert "testpassword" in url
        assert s.db_name in url

    def test_database_url_sync(self):
        s = Settings()
        url = s.database_url_sync("testpassword")
        assert "postgresql://" in url
        assert "+asyncpg" not in url

    def test_redis_url(self):
        s = Settings()
        url = s.redis_url("redispass")
        assert "redis://" in url
        assert "redispass" in url

    def test_default_temporal_enabled(self):
        """temporal_enabled defaults to True (full platform / proposal path)."""
        s = Settings()
        assert s.temporal_enabled is True

    def test_default_log_level(self):
        s = Settings()
        assert s.log_level == "INFO"

    def test_default_ws_max_connections(self):
        s = Settings()
        assert s.ws_max_connections == 100
