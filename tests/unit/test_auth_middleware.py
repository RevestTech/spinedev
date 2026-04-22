"""
Unit tests for API key authentication middleware.

Tests:
  - Missing API key → 401
  - Master key not configured → 500
  - Invalid API key → 403
  - Valid API key → returns key string
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from tron.api.middleware.auth import require_api_key


class TestRequireApiKey:

    async def test_missing_key_raises_401(self):
        request = MagicMock()
        request.app.state.secrets = {
            "auth/master-key": "mk",
            "auth/jwt-secret": "jwt-secret-at-least-32-chars-long!!",
        }
        request.cookies = {}
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(request, api_key=None)
        assert exc_info.value.status_code == 401

    async def test_master_key_not_configured_raises_500(self):
        request = MagicMock()
        request.app.state.secrets = {"auth/jwt-secret": "jwt-secret-at-least-32-chars-long!!"}
        request.cookies = {}
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(request, api_key="some-key")
        assert exc_info.value.status_code == 500

    async def test_invalid_key_raises_403(self):
        request = MagicMock()
        request.app.state.secrets = {
            "auth/master-key": "correct-key",
            "auth/jwt-secret": "jwt-secret-at-least-32-chars-long!!",
        }
        request.cookies = {}
        request.client.host = "127.0.0.1"
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(request, api_key="wrong-key")
        assert exc_info.value.status_code == 403

    async def test_valid_key_returns_key(self):
        request = MagicMock()
        request.app.state.secrets = {
            "auth/master-key": "my-key",
            "auth/jwt-secret": "jwt-secret-at-least-32-chars-long!!",
        }
        request.cookies = {}
        result = await require_api_key(request, api_key="my-key")
        assert result == "my-key"

    async def test_no_client_host_still_raises_403(self):
        """When request.client is None, should still raise 403."""
        request = MagicMock()
        request.app.state.secrets = {
            "auth/master-key": "real-key",
            "auth/jwt-secret": "jwt-secret-at-least-32-chars-long!!",
        }
        request.cookies = {}
        request.client = None
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(request, api_key="bad-key")
        assert exc_info.value.status_code == 403

    async def test_valid_admin_cookie_returns_session_marker(self):
        from tron.api.admin_session import ADMIN_COOKIE_NAME, issue_admin_jwt

        secret = "jwt-secret-at-least-32-chars-long!!"
        tok = issue_admin_jwt(secret, 3600)
        request = MagicMock()
        request.app.state.secrets = {"auth/master-key": "mk", "auth/jwt-secret": secret}
        request.cookies = {ADMIN_COOKIE_NAME: tok}
        result = await require_api_key(request, api_key=None)
        assert result == "__admin_ui_session__"
