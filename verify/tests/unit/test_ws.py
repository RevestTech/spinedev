"""
Unit tests for WebSocket route helpers.

Tests:
  - _authenticate_ws (valid token, missing token, no master key, auth disabled)
  - _send_json (success and failure)
  - Active connection tracking
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch


from tron.api.routes.ws import _authenticate_ws, _send_json, _active_connections


# ── _authenticate_ws Tests ───────────────────────────────────────────


class TestAuthenticateWs:

    async def test_auth_disabled_returns_true(self):
        """When ws_require_auth=False, auth always passes."""
        ws = MagicMock()
        with patch("tron.api.routes.ws.settings") as mock_settings:
            mock_settings.ws_require_auth = False
            result = await _authenticate_ws(ws)
        assert result is True

    async def test_missing_token_returns_false(self):
        """No token in query params → False."""
        ws = MagicMock()
        ws.query_params = {}
        ws.cookies = {}
        ws.app.state.secrets = {
            "auth/master-key": "mk",
            "auth/jwt-secret": "jwt-secret-at-least-32-chars-long!!",
        }
        with patch("tron.api.routes.ws.settings") as mock_settings:
            mock_settings.ws_require_auth = True
            result = await _authenticate_ws(ws)
        assert result is False

    async def test_valid_token_returns_true(self):
        """Correct token → True."""
        ws = MagicMock()
        ws.query_params = {"token": "master-key-123"}
        ws.cookies = {}
        ws.app.state.secrets = {
            "auth/master-key": "master-key-123",
            "auth/jwt-secret": "jwt-secret-at-least-32-chars-long!!",
        }
        with patch("tron.api.routes.ws.settings") as mock_settings:
            mock_settings.ws_require_auth = True
            result = await _authenticate_ws(ws)
        assert result is True

    async def test_wrong_token_returns_false(self):
        """Wrong token → False."""
        ws = MagicMock()
        ws.query_params = {"token": "wrong-key"}
        ws.cookies = {}
        ws.app.state.secrets = {
            "auth/master-key": "correct-key",
            "auth/jwt-secret": "jwt-secret-at-least-32-chars-long!!",
        }
        with patch("tron.api.routes.ws.settings") as mock_settings:
            mock_settings.ws_require_auth = True
            result = await _authenticate_ws(ws)
        assert result is False

    async def test_no_master_key_returns_false(self):
        """Master key not in secrets → False."""
        ws = MagicMock()
        ws.query_params = {"token": "some-key"}
        ws.app.state.secrets = {}  # No master key
        with patch("tron.api.routes.ws.settings") as mock_settings:
            mock_settings.ws_require_auth = True
            result = await _authenticate_ws(ws)
        assert result is False

    async def test_scoped_key_with_audits_scope_accepted(self):
        """Non-master API key with ``audits`` scope may open the audit WebSocket."""
        ws = MagicMock()
        ws.query_params = {"token": "scoped-secret"}
        ws.cookies = {}
        ws.app.state.secrets = {
            "auth/master-key": "master-only",
            "auth/jwt-secret": "jwt-secret-at-least-32-chars-long!!",
        }
        with (
            patch("tron.api.routes.ws.settings") as mock_settings,
            patch(
                "tron.api.routes.ws.lookup_scoped_api_key_scopes",
                new_callable=AsyncMock,
                return_value=frozenset({"audits"}),
            ),
        ):
            mock_settings.ws_require_auth = True
            result = await _authenticate_ws(ws)
        assert result is True

    async def test_scoped_key_without_audits_scope_rejected(self):
        ws = MagicMock()
        ws.query_params = {"token": "scoped-secret"}
        ws.cookies = {}
        ws.app.state.secrets = {
            "auth/master-key": "master-only",
            "auth/jwt-secret": "jwt-secret-at-least-32-chars-long!!",
        }
        with (
            patch("tron.api.routes.ws.settings") as mock_settings,
            patch(
                "tron.api.routes.ws.lookup_scoped_api_key_scopes",
                new_callable=AsyncMock,
                return_value=frozenset({"projects"}),
            ),
        ):
            mock_settings.ws_require_auth = True
            result = await _authenticate_ws(ws)
        assert result is False


# ── _send_json Tests ─────────────────────────────────────────────────


class TestSendJson:

    async def test_send_success(self):
        """Successful send → True."""
        ws = AsyncMock()
        ws.send_json = AsyncMock()
        result = await _send_json(ws, {"event": "test"})
        assert result is True
        ws.send_json.assert_called_once_with({"event": "test"})

    async def test_send_failure(self):
        """Connection error → False."""
        ws = AsyncMock()
        ws.send_json = AsyncMock(side_effect=RuntimeError("connection closed"))
        result = await _send_json(ws, {"event": "test"})
        assert result is False


# ── Active connections ───────────────────────────────────────────────


class TestActiveConnections:

    def test_active_connections_is_set(self):
        assert isinstance(_active_connections, set)
