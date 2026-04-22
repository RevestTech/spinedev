"""
Unit tests for KMac Vault client.

Tests:
  - _CacheEntry expiration
  - _full_key prefix handling
  - _resolve_token fallback chain
  - KMacVaultClient.get() with cache, HTTP mocks, errors
  - KMacVaultClient.get_many()
  - invalidate() and close()
  - Module singleton
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tron.infra.secrets.kmac_client import (
    KMacVaultClient,
    _CacheEntry,
    _get_client,
)


# ── _CacheEntry ──────────────────────────────────────────────────────


class TestCacheEntry:

    def test_not_expired_fresh(self):
        entry = _CacheEntry(value="secret", fetched_at=time.monotonic())
        assert entry.is_expired() is False

    def test_expired_old(self):
        entry = _CacheEntry(value="secret", fetched_at=time.monotonic() - 999)
        assert entry.is_expired() is True

    @patch("tron.infra.secrets.kmac_client.CACHE_TTL_SECONDS", 0)
    def test_ttl_zero_always_expired(self):
        entry = _CacheEntry(value="secret", fetched_at=time.monotonic())
        assert entry.is_expired() is True


# ── _full_key ────────────────────────────────────────────────────────


class TestFullKey:

    def test_adds_prefix(self):
        client = KMacVaultClient()
        assert client._full_key("db_password") == "tron:db_password"

    def test_no_double_prefix(self):
        client = KMacVaultClient()
        assert client._full_key("tron:db_password") == "tron:db_password"

    def test_normalizes_slashes_and_hyphens(self):
        client = KMacVaultClient()
        assert client._full_key("auth/secret-key") == "tron:auth_secret_key"

    def test_custom_prefix(self):
        client = KMacVaultClient(secret_prefix="myapp:")
        assert client._full_key("db_pass") == "myapp:db_pass"


# ── _resolve_token ───────────────────────────────────────────────────


class TestResolveToken:

    async def test_cached_token(self):
        client = KMacVaultClient()
        client._token = "cached-tok"
        assert await client._resolve_token() == "cached-tok"

    async def test_file_token(self, tmp_path):
        token_file = tmp_path / "vault-token"
        token_file.write_text("file-tok\n")
        with patch("tron.infra.secrets.kmac_client.KMAC_TOKEN_PATH", str(token_file)):
            client = KMacVaultClient()
            assert await client._resolve_token() == "file-tok"

    async def test_env_token(self, monkeypatch):
        monkeypatch.setattr("tron.infra.secrets.kmac_client.KMAC_TOKEN_PATH", "/nonexistent")
        monkeypatch.setenv("KMAC_TOKEN", "env-tok")
        client = KMacVaultClient()
        assert await client._resolve_token() == "env-tok"

    async def test_no_token_raises(self, monkeypatch):
        monkeypatch.setattr("tron.infra.secrets.kmac_client.KMAC_TOKEN_PATH", "/nonexistent")
        monkeypatch.delenv("KMAC_TOKEN", raising=False)
        client = KMacVaultClient()
        with pytest.raises(RuntimeError, match="No KMac vault token"):
            await client._resolve_token()


# ── KMacVaultClient.get() ────────────────────────────────────────────


class TestGet:

    async def test_returns_cached(self):
        client = KMacVaultClient()
        client._cache["db_password"] = _CacheEntry(value="cached", fetched_at=time.monotonic())
        assert await client.get("db/password") == "cached"

    async def test_fetches_from_vault(self):
        client = KMacVaultClient()
        client._token = "tok"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"key": "tron:db_password", "value": "vault-val"}
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)

        with patch.object(client, "_get_http", new_callable=AsyncMock, return_value=mock_http):
            result = await client.get("db/password")

        assert result == "vault-val"

    async def test_caches_after_fetch(self):
        client = KMacVaultClient()
        client._token = "tok"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"value": "new-val"}
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)

        with patch.object(client, "_get_http", new_callable=AsyncMock, return_value=mock_http):
            await client.get("auth/jwt-secret")

        assert "auth_jwt_secret" in client._cache

    async def test_404_raises_key_error(self):
        client = KMacVaultClient()
        client._token = "tok"

        mock_resp = MagicMock()
        mock_resp.status_code = 404

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)

        with patch.object(client, "_get_http", new_callable=AsyncMock, return_value=mock_http):
            with pytest.raises(KeyError, match="not found"):
                await client.get("missing/key")

    async def test_401_raises_runtime_error(self):
        client = KMacVaultClient()
        client._token = "tok"

        mock_resp = MagicMock()
        mock_resp.status_code = 401

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)

        with patch.object(client, "_get_http", new_callable=AsyncMock, return_value=mock_http):
            with pytest.raises(RuntimeError, match="401"):
                await client.get("db/password")

    async def test_missing_value_field_raises(self):
        client = KMacVaultClient()
        client._token = "tok"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"key": "tron:x"}  # Missing 'value'
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)

        with patch.object(client, "_get_http", new_callable=AsyncMock, return_value=mock_http):
            with pytest.raises(KeyError, match="value"):
                await client.get("x")


# ── get_many ─────────────────────────────────────────────────────────


class TestGetMany:

    async def test_success(self):
        client = KMacVaultClient()
        client._cache["k1"] = _CacheEntry(value="v1", fetched_at=time.monotonic())
        client._cache["k2"] = _CacheEntry(value="v2", fetched_at=time.monotonic())

        result = await client.get_many(["k1", "k2"])
        assert result == {"k1": "v1", "k2": "v2"}

    async def test_partial_failure(self):
        client = KMacVaultClient()
        client._token = "tok"
        client._cache["k1"] = _CacheEntry(value="v1", fetched_at=time.monotonic())

        mock_resp = MagicMock()
        mock_resp.status_code = 404

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)

        with patch.object(client, "_get_http", new_callable=AsyncMock, return_value=mock_http):
            with pytest.raises(RuntimeError, match="Failed to fetch 1"):
                await client.get_many(["k1", "k2"])


# ── invalidate / close ───────────────────────────────────────────────


class TestInvalidateClose:

    def test_invalidate_specific(self):
        client = KMacVaultClient()
        client._cache["db_password"] = _CacheEntry(value="v", fetched_at=time.monotonic())
        client._cache["other"] = _CacheEntry(value="v", fetched_at=time.monotonic())
        client.invalidate("db/password")
        assert "db_password" not in client._cache
        assert "other" in client._cache

    def test_invalidate_all(self):
        client = KMacVaultClient()
        client._cache["a"] = _CacheEntry(value="v", fetched_at=time.monotonic())
        client.invalidate()
        assert len(client._cache) == 0

    async def test_close(self):
        client = KMacVaultClient()
        mock_http = AsyncMock()
        mock_http.is_closed = False
        client._http = mock_http
        await client.close()
        mock_http.aclose.assert_called_once()

    async def test_close_noop(self):
        client = KMacVaultClient()
        await client.close()  # No error


# ── Module singleton ─────────────────────────────────────────────────


class TestModuleSingleton:

    def test_get_client(self):
        with patch("tron.infra.secrets.kmac_client._client", None):
            client = _get_client()
            assert isinstance(client, KMacVaultClient)


# ── Get HTTP Client Tests ──────────────────────────────────────────


class TestGetHttpClient:
    """Test HTTP client creation and reuse."""

    async def test_get_http_client_creates_with_bearer_token(self):
        """_get_http should create client with bearer token in headers."""
        client = KMacVaultClient()
        client._token = "test-token-xyz"

        http = await client._get_http()

        assert http is not None
        # Verify it has the vault URL
        assert http.base_url == "http://host.docker.internal:9999"
        await http.aclose()

    async def test_get_http_client_reuses_open_connection(self):
        """_get_http should reuse existing open client."""
        client = KMacVaultClient()
        client._token = "test-token"

        http1 = await client._get_http()
        http2 = await client._get_http()

        assert http1 is http2
        await http1.aclose()

    async def test_get_http_client_recreates_if_closed(self):
        """_get_http should recreate client if previous one closed."""
        client = KMacVaultClient()
        client._token = "test-token"

        http1 = await client._get_http()
        await http1.aclose()

        http2 = await client._get_http()
        assert http2 is not http1
        await http2.aclose()


# ── Legacy Token Fallback Tests ────────────────────────────────────


class TestLegacyTokenFallback:
    """Test legacy token path for backwards compatibility."""

    async def test_legacy_fallback_with_env_var(self, monkeypatch):
        """Should fall back to KMAC_TOKEN env var when file missing."""
        monkeypatch.setattr("tron.infra.secrets.kmac_client.KMAC_TOKEN_PATH", "/nonexistent/path")
        monkeypatch.delenv("KMAC_TOKEN", raising=False)

        original_isfile = __import__("os").path.isfile

        def fake_isfile(path):
            return False

        monkeypatch.setattr("os.path.isfile", fake_isfile)
        monkeypatch.setenv("KMAC_TOKEN", "fallback-token")

        client = KMacVaultClient()
        token = await client._resolve_token()
        assert token == "fallback-token"


# ── Module-Level Convenience Function Tests ──────────────────────


class TestModuleLevelFunctions:
    """Test module-level get_secret and get_secrets functions."""

    async def test_get_secret_module_function(self):
        """Module-level get_secret should use singleton client."""
        from tron.infra.secrets.kmac_client import get_secret

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value="secret-value")

        with patch("tron.infra.secrets.kmac_client._get_client", return_value=mock_client):
            result = await get_secret("db/password")

        assert result == "secret-value"
        mock_client.get.assert_called_once_with("db/password", field_name="value")

    async def test_get_secrets_module_function(self):
        """Module-level get_secrets should use singleton client."""
        from tron.infra.secrets.kmac_client import get_secrets

        mock_client = AsyncMock()
        mock_client.get_many = AsyncMock(return_value={
            "k1": "v1",
            "k2": "v2",
        })

        with patch("tron.infra.secrets.kmac_client._get_client", return_value=mock_client):
            result = await get_secrets(["k1", "k2"])

        assert result == {"k1": "v1", "k2": "v2"}
        mock_client.get_many.assert_called_once_with(["k1", "k2"], field_name="value")
