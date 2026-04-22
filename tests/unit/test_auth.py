"""
Unit tests for API key authentication middleware.

Tests:
  - Valid API key → passes
  - Missing API key → 401
  - Invalid API key → 403
  - Missing master key in app state → 500
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from tron.api.middleware.auth import require_api_key


def _make_request(api_key_in_state: str | None) -> MagicMock:
    """Create a mock Request with app.state.secrets."""
    request = MagicMock()
    request.state = MagicMock()
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    if api_key_in_state:
        request.app.state.secrets = {"auth/master-key": api_key_in_state}
    else:
        request.app.state.secrets = {}
    return request


class TestRequireAPIKey:

    async def test_valid_key(self):
        """Correct key → returns the key."""
        request = _make_request("my-secret-key")
        result = await require_api_key(request, api_key="my-secret-key")
        assert result == "my-secret-key"
        assert request.state.api_key_is_master is True
        assert "*" in request.state.api_key_scopes

    async def test_missing_key(self):
        """No API key header → 401."""
        request = _make_request("my-secret-key")
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(request, api_key=None)
        assert exc_info.value.status_code == 401

    async def test_invalid_key(self):
        """Wrong API key → 403."""
        request = _make_request("my-secret-key")
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(request, api_key="wrong-key")
        assert exc_info.value.status_code == 403

    async def test_no_master_key_configured(self):
        """Master key not in app state → 500."""
        request = _make_request(None)
        with pytest.raises(HTTPException) as exc_info:
            await require_api_key(request, api_key="any-key")
        assert exc_info.value.status_code == 500
