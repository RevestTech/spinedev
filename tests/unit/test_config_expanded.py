"""
Expanded unit tests for application configuration.

Tests coverage for:
  - Default values for all settings
  - Constructor override via kwargs
  - Type checking and immutability
  - URL builder methods
  - Edge cases (special characters, boundary values)
  - Environment variable integration (via module reimport)
"""

from __future__ import annotations

import importlib
import os
import sys
from unittest.mock import patch

import pytest

from tron.api.config import Settings


# ── Default Values ──


class TestSettingsDefaults:
    """Verify every default matches the expected value."""

    def test_default_db_host(self):
        s = Settings()
        assert s.db_host == os.getenv("DB_HOST", "pgbouncer")

    def test_default_db_port(self):
        s = Settings()
        assert s.db_port == int(os.getenv("DB_PORT", "5432"))

    def test_default_db_name(self):
        s = Settings()
        assert s.db_name == os.getenv("DB_NAME", "tron")

    def test_default_db_user(self):
        s = Settings()
        assert s.db_user == os.getenv("DB_USER", "tron")

    def test_default_db_pool_size(self):
        s = Settings()
        assert s.db_pool_size == int(os.getenv("DB_POOL_SIZE", "10"))

    def test_default_db_max_overflow(self):
        s = Settings()
        assert s.db_max_overflow == int(os.getenv("DB_MAX_OVERFLOW", "5"))

    def test_default_redis_host(self):
        s = Settings()
        assert s.redis_host == os.getenv("REDIS_HOST", "redis")

    def test_default_redis_port(self):
        s = Settings()
        assert s.redis_port == int(os.getenv("REDIS_PORT", "6379"))

    def test_default_redis_db(self):
        s = Settings()
        assert s.redis_db == int(os.getenv("REDIS_DB", "0"))

    def test_default_redis_pool_size(self):
        s = Settings()
        assert s.redis_pool_size == int(os.getenv("REDIS_POOL_SIZE", "50"))

    def test_default_minio_endpoint(self):
        s = Settings()
        assert s.minio_endpoint == os.getenv("MINIO_ENDPOINT", "minio:9000")

    def test_default_minio_secure(self):
        s = Settings()
        assert s.minio_secure == (os.getenv("MINIO_SECURE", "true").lower() == "true")

    def test_default_minio_bucket(self):
        s = Settings()
        assert s.minio_bucket == os.getenv("MINIO_BUCKET", "tron-artifacts")

    def test_default_temporal_host(self):
        s = Settings()
        assert s.temporal_host == os.getenv("TEMPORAL_HOST", "temporal:7233")

    def test_default_temporal_task_queue(self):
        s = Settings()
        assert s.temporal_task_queue == os.getenv("TEMPORAL_TASK_QUEUE", "tron-tasks")

    def test_default_temporal_enabled(self):
        s = Settings()
        assert s.temporal_enabled == (os.getenv("TEMPORAL_ENABLED", "true").lower() == "true")

    def test_default_jwt_algorithm(self):
        s = Settings()
        assert s.jwt_algorithm == os.getenv("JWT_ALGORITHM", "HS256")

    def test_default_jwt_expiration_minutes(self):
        s = Settings()
        assert s.jwt_expiration_minutes == int(os.getenv("JWT_EXPIRATION_MINUTES", "60"))

    def test_default_rate_limit_per_minute(self):
        s = Settings()
        assert s.rate_limit_per_minute == int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))

    def test_default_rate_limit_per_hour(self):
        s = Settings()
        assert s.rate_limit_per_hour == int(os.getenv("RATE_LIMIT_PER_HOUR", "1000"))

    def test_default_log_level(self):
        s = Settings()
        assert s.log_level == os.getenv("LOG_LEVEL", "INFO")

    def test_default_workers(self):
        s = Settings()
        assert s.workers == int(os.getenv("WORKERS", "1"))

    def test_default_debug(self):
        s = Settings()
        assert s.debug == (os.getenv("DEBUG", "false").lower() == "true")

    def test_default_ws_require_auth(self):
        s = Settings()
        assert s.ws_require_auth == (os.getenv("WS_REQUIRE_AUTH", "true").lower() == "true")

    def test_default_ws_max_connections(self):
        s = Settings()
        assert s.ws_max_connections == int(os.getenv("WS_MAX_CONNECTIONS", "100"))

    def test_default_llm_circuit_breaker_threshold(self):
        s = Settings()
        assert s.llm_circuit_breaker_threshold == int(os.getenv("LLM_CIRCUIT_BREAKER_THRESHOLD", "5"))

    def test_default_llm_circuit_breaker_timeout(self):
        s = Settings()
        assert s.llm_circuit_breaker_timeout == int(os.getenv("LLM_CIRCUIT_BREAKER_TIMEOUT", "60"))

    def test_default_llm_request_timeout(self):
        s = Settings()
        assert s.llm_request_timeout == int(os.getenv("LLM_REQUEST_TIMEOUT", "30"))

    def test_default_llm_bulkhead_max_concurrent(self):
        s = Settings()
        assert s.llm_bulkhead_max_concurrent == int(os.getenv("LLM_BULKHEAD_MAX_CONCURRENT", "10"))

    def test_default_otel_endpoint(self):
        s = Settings()
        assert s.otel_endpoint == os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")

    def test_default_otel_enabled(self):
        s = Settings()
        assert s.otel_enabled == (os.getenv("OTEL_ENABLED", "true").lower() == "true")

    def test_default_otel_trace_sample_rate(self):
        s = Settings()
        assert s.otel_trace_sample_rate == float(os.getenv("OTEL_TRACE_SAMPLE_RATE", "1.0"))

    def test_default_service_name(self):
        s = Settings()
        assert s.service_name == os.getenv("OTEL_SERVICE_NAME", "tron-api")


# ── Constructor Overrides (kwargs) ──


class TestConstructorOverrides:
    """Test that Settings can be constructed with explicit kwargs."""

    def test_override_db_host(self):
        s = Settings(db_host="custom-db")
        assert s.db_host == "custom-db"

    def test_override_db_port(self):
        s = Settings(db_port=5433)
        assert s.db_port == 5433

    def test_override_db_name(self):
        s = Settings(db_name="custom-db")
        assert s.db_name == "custom-db"

    def test_override_db_user(self):
        s = Settings(db_user="custom-user")
        assert s.db_user == "custom-user"

    def test_override_db_pool_size(self):
        s = Settings(db_pool_size=20)
        assert s.db_pool_size == 20

    def test_override_db_max_overflow(self):
        s = Settings(db_max_overflow=10)
        assert s.db_max_overflow == 10

    def test_override_redis_host(self):
        s = Settings(redis_host="custom-redis")
        assert s.redis_host == "custom-redis"

    def test_override_redis_port(self):
        s = Settings(redis_port=6380)
        assert s.redis_port == 6380

    def test_override_redis_db(self):
        s = Settings(redis_db=5)
        assert s.redis_db == 5

    def test_override_redis_pool_size(self):
        s = Settings(redis_pool_size=100)
        assert s.redis_pool_size == 100

    def test_override_workers(self):
        s = Settings(workers=4)
        assert s.workers == 4

    def test_override_log_level(self):
        s = Settings(log_level="DEBUG")
        assert s.log_level == "DEBUG"

    def test_override_debug(self):
        s = Settings(debug=True)
        assert s.debug is True

    def test_override_temporal_enabled(self):
        s = Settings(temporal_enabled=True)
        assert s.temporal_enabled is True

    def test_override_minio_secure(self):
        s = Settings(minio_secure=False)
        assert s.minio_secure is False

    def test_override_jwt_algorithm(self):
        s = Settings(jwt_algorithm="RS256")
        assert s.jwt_algorithm == "RS256"

    def test_override_jwt_expiration_minutes(self):
        s = Settings(jwt_expiration_minutes=120)
        assert s.jwt_expiration_minutes == 120

    def test_override_rate_limit_per_minute(self):
        s = Settings(rate_limit_per_minute=100)
        assert s.rate_limit_per_minute == 100

    def test_override_rate_limit_per_hour(self):
        s = Settings(rate_limit_per_hour=2000)
        assert s.rate_limit_per_hour == 2000

    def test_override_ws_max_connections(self):
        s = Settings(ws_max_connections=500)
        assert s.ws_max_connections == 500

    def test_override_ws_require_auth(self):
        s = Settings(ws_require_auth=False)
        assert s.ws_require_auth is False

    def test_override_otel_trace_sample_rate(self):
        s = Settings(otel_trace_sample_rate=0.5)
        assert s.otel_trace_sample_rate == 0.5

    def test_override_service_name(self):
        s = Settings(service_name="custom-service")
        assert s.service_name == "custom-service"

    def test_override_minio_bucket(self):
        s = Settings(minio_bucket="custom-bucket")
        assert s.minio_bucket == "custom-bucket"

    def test_override_temporal_task_queue(self):
        s = Settings(temporal_task_queue="custom-queue")
        assert s.temporal_task_queue == "custom-queue"

    def test_override_llm_circuit_breaker_threshold(self):
        s = Settings(llm_circuit_breaker_threshold=10)
        assert s.llm_circuit_breaker_threshold == 10

    def test_override_llm_request_timeout(self):
        s = Settings(llm_request_timeout=60)
        assert s.llm_request_timeout == 60

    def test_override_multiple_fields(self):
        s = Settings(db_host="custom", db_port=9999, workers=8, debug=True)
        assert s.db_host == "custom"
        assert s.db_port == 9999
        assert s.workers == 8
        assert s.debug is True


# ── Environment Variable Integration (module reimport) ──


class TestEnvironmentVariableIntegration:
    """Test env var integration by reimporting the module."""

    @pytest.fixture(autouse=True)
    def _save_module(self):
        """Save and restore the config module across each test."""
        saved = sys.modules.get("tron.api.config")
        yield
        if saved is not None:
            sys.modules["tron.api.config"] = saved
        elif "tron.api.config" in sys.modules:
            del sys.modules["tron.api.config"]

    def _reimport_settings(self):
        if "tron.api.config" in sys.modules:
            del sys.modules["tron.api.config"]
        mod = importlib.import_module("tron.api.config")
        return mod.Settings()

    def test_env_override_db_host(self):
        with patch.dict(os.environ, {"DB_HOST": "custom-db"}):
            s = self._reimport_settings()
            assert s.db_host == "custom-db"

    def test_env_override_db_port(self):
        with patch.dict(os.environ, {"DB_PORT": "5433"}):
            s = self._reimport_settings()
            assert s.db_port == 5433

    def test_env_override_workers(self):
        with patch.dict(os.environ, {"WORKERS": "4"}):
            s = self._reimport_settings()
            assert s.workers == 4

    def test_env_override_log_level(self):
        with patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"}):
            s = self._reimport_settings()
            assert s.log_level == "DEBUG"

    def test_env_override_debug_true(self):
        with patch.dict(os.environ, {"DEBUG": "true"}):
            s = self._reimport_settings()
            assert s.debug is True

    def test_env_override_temporal_enabled_true(self):
        with patch.dict(os.environ, {"TEMPORAL_ENABLED": "true"}):
            s = self._reimport_settings()
            assert s.temporal_enabled is True

    def test_env_override_minio_secure_false(self):
        with patch.dict(os.environ, {"MINIO_SECURE": "false"}):
            s = self._reimport_settings()
            assert s.minio_secure is False

    def test_env_override_otel_enabled_false(self):
        with patch.dict(os.environ, {"OTEL_ENABLED": "false"}):
            s = self._reimport_settings()
            assert s.otel_enabled is False

    def test_env_override_sample_rate(self):
        with patch.dict(os.environ, {"OTEL_TRACE_SAMPLE_RATE": "0.25"}):
            s = self._reimport_settings()
            assert s.otel_trace_sample_rate == 0.25

    def test_env_override_multiple(self):
        env = {"DB_HOST": "myhost", "DB_PORT": "9999", "WORKERS": "8"}
        with patch.dict(os.environ, env):
            s = self._reimport_settings()
            assert s.db_host == "myhost"
            assert s.db_port == 9999
            assert s.workers == 8


# ── Type Checking ──


class TestTypeChecking:
    """Verify field types on default Settings."""

    def test_db_port_is_int(self):
        s = Settings()
        assert isinstance(s.db_port, int)

    def test_redis_port_is_int(self):
        s = Settings()
        assert isinstance(s.redis_port, int)

    def test_db_pool_size_is_int(self):
        s = Settings()
        assert isinstance(s.db_pool_size, int)

    def test_workers_is_int(self):
        s = Settings()
        assert isinstance(s.workers, int)

    def test_jwt_expiration_is_int(self):
        s = Settings()
        assert isinstance(s.jwt_expiration_minutes, int)

    def test_rate_limit_per_minute_is_int(self):
        s = Settings()
        assert isinstance(s.rate_limit_per_minute, int)

    def test_otel_trace_sample_rate_is_float(self):
        s = Settings()
        assert isinstance(s.otel_trace_sample_rate, float)

    def test_debug_is_bool(self):
        s = Settings()
        assert isinstance(s.debug, bool)

    def test_temporal_enabled_is_bool(self):
        s = Settings()
        assert isinstance(s.temporal_enabled, bool)

    def test_minio_secure_is_bool(self):
        s = Settings()
        assert isinstance(s.minio_secure, bool)

    def test_otel_enabled_is_bool(self):
        s = Settings()
        assert isinstance(s.otel_enabled, bool)

    def test_ws_require_auth_is_bool(self):
        s = Settings()
        assert isinstance(s.ws_require_auth, bool)

    def test_db_host_is_str(self):
        s = Settings()
        assert isinstance(s.db_host, str)

    def test_service_name_is_str(self):
        s = Settings()
        assert isinstance(s.service_name, str)


# ── Immutability ──


class TestSettingsImmutability:
    """Test that Settings is frozen (immutable)."""

    def test_cannot_change_db_host(self):
        s = Settings()
        with pytest.raises(AttributeError):
            s.db_host = "modified"

    def test_cannot_change_db_port(self):
        s = Settings()
        with pytest.raises(AttributeError):
            s.db_port = 9999

    def test_cannot_add_new_attribute(self):
        s = Settings()
        with pytest.raises(AttributeError):
            s.new_attribute = "value"

    def test_cannot_change_debug(self):
        s = Settings()
        with pytest.raises(AttributeError):
            s.debug = True

    def test_cannot_change_workers(self):
        s = Settings()
        with pytest.raises(AttributeError):
            s.workers = 99


# ── URL Builders ──


class TestURLBuilders:
    """Test database and Redis URL builder methods."""

    def test_database_url_format(self):
        s = Settings(db_user="u", db_host="h", db_port=5432, db_name="d")
        url = s.database_url("pw")
        assert url == "postgresql+asyncpg://u:pw@h:5432/d"

    def test_database_url_sync_format(self):
        s = Settings(db_user="u", db_host="h", db_port=5432, db_name="d")
        url = s.database_url_sync("pw")
        assert url == "postgresql://u:pw@h:5432/d"

    def test_redis_url_format(self):
        s = Settings(redis_host="r", redis_port=6379, redis_db=0)
        url = s.redis_url("pw")
        assert url == "redis://:pw@r:6379/0"

    def test_database_url_contains_password(self):
        s = Settings()
        url = s.database_url("secret123")
        assert "secret123" in url

    def test_database_url_sync_no_asyncpg(self):
        s = Settings()
        url = s.database_url_sync("pw")
        assert "+asyncpg" not in url
        assert url.startswith("postgresql://")

    def test_database_url_uses_asyncpg(self):
        s = Settings()
        url = s.database_url("pw")
        assert "+asyncpg" in url

    def test_redis_url_with_different_db(self):
        s = Settings(redis_db=5)
        url = s.redis_url("pw")
        assert url.endswith("/5")

    def test_database_url_special_chars_password(self):
        s = Settings(db_user="u", db_host="h", db_port=5432, db_name="d")
        url = s.database_url("p@ss:w0rd")
        assert "p@ss:w0rd" in url

    def test_redis_url_empty_password(self):
        s = Settings(redis_host="r", redis_port=6379, redis_db=0)
        url = s.redis_url("")
        assert url == "redis://:@r:6379/0"


# ── Edge Cases ──


class TestEdgeCases:
    """Test boundary and edge-case values."""

    def test_very_large_port(self):
        s = Settings(db_port=65535)
        assert s.db_port == 65535

    def test_port_zero(self):
        s = Settings(db_port=0)
        assert s.db_port == 0

    def test_zero_workers(self):
        s = Settings(workers=0)
        assert s.workers == 0

    def test_large_pool_size(self):
        s = Settings(db_pool_size=10000)
        assert s.db_pool_size == 10000

    def test_long_hostname(self):
        host = "a" * 200 + ".example.com"
        s = Settings(db_host=host)
        assert s.db_host == host

    def test_special_characters_user(self):
        s = Settings(db_user="user-name_with.dots")
        assert s.db_user == "user-name_with.dots"

    def test_zero_rate_limit(self):
        s = Settings(rate_limit_per_minute=0, rate_limit_per_hour=0)
        assert s.rate_limit_per_minute == 0
        assert s.rate_limit_per_hour == 0

    def test_zero_jwt_expiration(self):
        s = Settings(jwt_expiration_minutes=0)
        assert s.jwt_expiration_minutes == 0

    def test_sample_rate_zero(self):
        s = Settings(otel_trace_sample_rate=0.0)
        assert s.otel_trace_sample_rate == 0.0

    def test_sample_rate_one(self):
        s = Settings(otel_trace_sample_rate=1.0)
        assert s.otel_trace_sample_rate == 1.0

    def test_sample_rate_fractional(self):
        s = Settings(otel_trace_sample_rate=0.333)
        assert s.otel_trace_sample_rate == 0.333

    def test_large_ws_max_connections(self):
        s = Settings(ws_max_connections=100000)
        assert s.ws_max_connections == 100000

    def test_long_bucket_name(self):
        s = Settings(minio_bucket="a" * 100)
        assert s.minio_bucket == "a" * 100

    def test_log_level_variants(self):
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            s = Settings(log_level=level)
            assert s.log_level == level


# ── Singleton ──


class TestSingleton:
    """Test that the module-level `settings` singleton exists."""

    def test_singleton_exists(self):
        from tron.api.config import settings
        assert isinstance(settings, Settings)

    def test_singleton_is_settings_instance(self):
        from tron.api.config import settings
        assert hasattr(settings, "db_host")
        assert hasattr(settings, "database_url")
        assert hasattr(settings, "redis_url")
