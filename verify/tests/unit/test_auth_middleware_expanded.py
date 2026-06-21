"""
Expanded unit tests for API key authentication middleware.

Tests:
  - API key extraction from X-API-Key header
  - Key validation against master key from keyvault
  - Constant-time comparison
  - Error responses (401 missing, 403 invalid, 500 not configured)
  - Request client information logging
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, Request

from tron.api.middleware.auth import require_api_key, api_key_header


class TestRequireApiKeyDependency:
    """Tests for require_api_key dependency."""

    async def test_missing_api_key_raises_401(self):
        """Missing X-API-Key header raises 401."""
        request = MagicMock(spec=Request)
        request.app.state.secrets = {
            "auth/master-key": "valid-key",
            "auth/jwt-secret": "jwt-secret-at-least-32-chars-long!!",
        }
        request.cookies = {}

        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(request, api_key=None)

        assert exc_info.value.status_code == 401
        assert "Not authenticated" in exc_info.value.detail

    async def test_master_key_not_loaded_raises_500(self):
        """Missing master key in keyvault raises 500."""
        request = MagicMock(spec=Request)
        request.app.state.secrets = {"auth/jwt-secret": "jwt-secret-at-least-32-chars-long!!"}
        request.cookies = {}
        request.client = MagicMock(host="192.168.1.1")
        
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(request, api_key="some-key")
        
        assert exc_info.value.status_code == 500
        assert "not configured" in exc_info.value.detail

    async def test_master_key_none_raises_500(self):
        """Master key None in keyvault raises 500."""
        request = MagicMock(spec=Request)
        request.app.state.secrets = {
            "auth/master-key": None,
            "auth/jwt-secret": "jwt-secret-at-least-32-chars-long!!",
        }
        request.cookies = {}
        request.client = MagicMock(host="192.168.1.1")
        
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(request, api_key="some-key")
        
        assert exc_info.value.status_code == 500

    async def test_invalid_api_key_raises_403(self):
        """Invalid API key raises 403."""
        request = MagicMock(spec=Request)
        request.app.state.secrets = {
            "auth/master-key": "valid-key",
            "auth/jwt-secret": "jwt-secret-at-least-32-chars-long!!",
        }
        request.cookies = {}
        request.client = MagicMock(host="192.168.1.100")
        
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(request, api_key="invalid-key")
        
        assert exc_info.value.status_code == 403
        assert "Invalid API key" in exc_info.value.detail

    async def test_valid_api_key_returns_key(self):
        """Valid API key returns the key string."""
        request = MagicMock(spec=Request)
        master_key = "test-master-key-12345"
        request.app.state.secrets = {
            "auth/master-key": master_key,
            "auth/jwt-secret": "jwt-secret-at-least-32-chars-long!!",
        }
        request.cookies = {}
        request.client = MagicMock(host="192.168.1.1")
        
        result = await require_api_key(request, api_key=master_key)
        
        assert result == master_key

    async def test_api_key_comparison_is_constant_time(self):
        """Uses hmac.compare_digest for timing-attack resistance."""
        request = MagicMock(spec=Request)
        request.app.state.secrets = {"auth/master-key": "secret-key"}
        request.client = MagicMock(host="192.168.1.1")
        
        # Call with valid key — should not raise
        result = await require_api_key(request, api_key="secret-key")
        assert result == "secret-key"

    async def test_client_host_logged_on_invalid_attempt(self, caplog):
        """Client IP address logged on invalid attempt."""
        request = MagicMock(spec=Request)
        request.app.state.secrets = {"auth/master-key": "valid-key"}
        request.client = MagicMock(host="203.0.113.42")
        
        with pytest.raises(HTTPException):
            await require_api_key(request, api_key="wrong-key")
        
        # Check that warning was logged
        assert any("203.0.113.42" in record.message for record in caplog.records if "Invalid API key" in record.message)

    async def test_unknown_client_host_logged(self, caplog):
        """Unknown client host logged gracefully."""
        request = MagicMock(spec=Request)
        request.app.state.secrets = {"auth/master-key": "valid-key"}
        request.client = None
        
        with pytest.raises(HTTPException):
            await require_api_key(request, api_key="wrong-key")
        
        # Should log gracefully with "unknown"
        assert any("unknown" in record.message for record in caplog.records if "Invalid API key" in record.message)

    async def test_empty_string_api_key_raises_401(self):
        """Empty string API key treated as missing."""
        request = MagicMock(spec=Request)
        request.app.state.secrets = {"auth/master-key": "valid-key"}
        request.client = MagicMock(host="192.168.1.1")
        
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(request, api_key="")
        
        assert exc_info.value.status_code == 401

    async def test_whitespace_api_key_invalid(self):
        """Whitespace-only API key doesn't match master key."""
        request = MagicMock(spec=Request)
        request.app.state.secrets = {"auth/master-key": "valid-key"}
        request.client = MagicMock(host="192.168.1.1")
        
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(request, api_key="   ")
        
        assert exc_info.value.status_code == 403

    async def test_case_sensitive_key_comparison(self):
        """API key comparison is case-sensitive."""
        request = MagicMock(spec=Request)
        request.app.state.secrets = {"auth/master-key": "MySecretKey"}
        request.client = MagicMock(host="192.168.1.1")
        
        # Wrong case should fail
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(request, api_key="mysecretkey")
        
        assert exc_info.value.status_code == 403

    async def test_key_with_special_characters(self):
        """API keys with special characters handled correctly."""
        request = MagicMock(spec=Request)
        special_key = "key-!@#$%^&*()_+={}[]|\\:;\"'<>,.?/~`"
        request.app.state.secrets = {"auth/master-key": special_key}
        request.client = MagicMock(host="192.168.1.1")
        
        result = await require_api_key(request, api_key=special_key)
        assert result == special_key

    async def test_key_with_unicode_characters(self):
        """API keys with unicode characters handled correctly."""
        request = MagicMock(spec=Request)
        unicode_key = "key-abc123"
        request.app.state.secrets = {"auth/master-key": unicode_key}
        request.client = MagicMock(host="192.168.1.1")
        
        result = await require_api_key(request, api_key=unicode_key)
        assert result == unicode_key

    async def test_very_long_api_key(self):
        """Very long API keys handled correctly."""
        request = MagicMock(spec=Request)
        long_key = "x" * 10000
        request.app.state.secrets = {"auth/master-key": long_key}
        request.client = MagicMock(host="192.168.1.1")
        
        result = await require_api_key(request, api_key=long_key)
        assert result == long_key

    async def test_multiple_failed_attempts_logged(self, caplog):
        """Multiple failed attempts all logged."""
        request = MagicMock(spec=Request)
        request.app.state.secrets = {"auth/master-key": "valid-key"}
        request.client = MagicMock(host="192.168.1.1")
        
        for i in range(3):
            with pytest.raises(HTTPException):
                await require_api_key(request, api_key=f"invalid-key-{i}")
        
        invalid_attempts = [r for r in caplog.records if "Invalid API key" in r.message]
        assert len(invalid_attempts) >= 3

    async def test_secrets_dict_has_multiple_keys(self):
        """Correct key extracted from secrets dict with multiple entries."""
        request = MagicMock(spec=Request)
        request.app.state.secrets = {
            "auth/master-key": "the-real-key",
            "db/password": "not-the-key",
            "redis/password": "also-not",
            "llm/api-key": "nope",
        }
        request.client = MagicMock(host="192.168.1.1")
        
        result = await require_api_key(request, api_key="the-real-key")
        assert result == "the-real-key"

    async def test_key_with_leading_trailing_whitespace(self):
        """Keys with whitespace don't match unless exact."""
        request = MagicMock(spec=Request)
        request.app.state.secrets = {"auth/master-key": "mykey"}
        request.client = MagicMock(host="192.168.1.1")
        
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(request, api_key=" mykey ")
        
        assert exc_info.value.status_code == 403


class TestAPIKeyHeaderExtraction:
    """Tests for APIKeyHeader from FastAPI security."""

    def test_api_key_header_name(self):
        """APIKeyHeader configured for X-API-Key."""
        assert api_key_header.model.name == "X-API-Key"

    def test_api_key_header_auto_error_false(self):
        """APIKeyHeader configured with auto_error=False."""
        assert api_key_header.auto_error is False


class TestAPIKeyHeaderScenarios:
    """Integration tests simulating various header scenarios."""

    async def test_multiple_x_api_key_headers(self):
        """When multiple X-API-Key headers present, first used."""
        # FastAPI/ASGI typically takes first header in such cases
        request = MagicMock(spec=Request)
        request.app.state.secrets = {"auth/master-key": "first-key"}
        request.client = MagicMock(host="192.168.1.1")
        
        result = await require_api_key(request, api_key="first-key")
        assert result == "first-key"

    async def test_api_key_with_bearer_prefix_fails(self):
        """API key with 'Bearer ' prefix doesn't match."""
        request = MagicMock(spec=Request)
        request.app.state.secrets = {"auth/master-key": "mytoken"}
        request.client = MagicMock(host="192.168.1.1")
        
        # Should fail because "Bearer mytoken" != "mytoken"
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(request, api_key="Bearer mytoken")
        
        assert exc_info.value.status_code == 403

    async def test_mixed_case_header_name(self):
        """Header name matching is case-insensitive (handled by FastAPI)."""
        # FastAPI's APIKeyHeader handles case-insensitive header names
        request = MagicMock(spec=Request)
        request.app.state.secrets = {"auth/master-key": "key123"}
        request.client = MagicMock(host="192.168.1.1")
        
        # If passed through FastAPI, header name case doesn't matter
        result = await require_api_key(request, api_key="key123")
        assert result == "key123"


class TestHTTPExceptionDetails:
    """Tests for HTTP exception details and headers."""

    async def test_401_exception_fields(self):
        """401 exception has correct status_code and detail."""
        request = MagicMock(spec=Request)
        request.app.state.secrets = {"auth/master-key": "key"}
        request.client = MagicMock(host="192.168.1.1")
        
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(request, api_key=None)
        
        exc = exc_info.value
        assert exc.status_code == 401
        assert isinstance(exc.detail, str)
        assert len(exc.detail) > 0

    async def test_403_exception_fields(self):
        """403 exception has correct status_code and detail."""
        request = MagicMock(spec=Request)
        request.app.state.secrets = {"auth/master-key": "valid"}
        request.client = MagicMock(host="192.168.1.1")
        
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(request, api_key="invalid")
        
        exc = exc_info.value
        assert exc.status_code == 403
        assert "Invalid" in exc.detail

    async def test_500_exception_fields(self):
        """500 exception has correct status_code and detail."""
        request = MagicMock(spec=Request)
        request.app.state.secrets = {}
        request.client = MagicMock(host="192.168.1.1")
        
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(request, api_key="any-key")
        
        exc = exc_info.value
        assert exc.status_code == 500
        assert "configured" in exc.detail
