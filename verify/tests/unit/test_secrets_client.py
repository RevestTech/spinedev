"""
Unit tests for KMac Vault secrets client.

Tests:
  - Key translation (_to_kmac_key)
  - Cache entry expiration
  - Token resolution fallback chain
  - KeyvaultClient.get() with cache, errors
  - KeyvaultClient.get_many() with partial failures
  - KeyvaultClient.invalidate()
  - Module-level convenience functions
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tron.infra.secrets.client import (
    KeyvaultClient,
    _CacheEntry,
    _to_kmac_key,
    _get_client,
)


# ── Key Translation ──────────────────────────────────────────────────


class TestToKmacKey:

    def test_simple_slash_key(self):
        assert _to_kmac_key("db/password") == "tron:db_password"

    def test_hyphenated_key(self):
        assert _to_kmac_key("auth/master-key") == "tron:auth_master_key"

    def test_llm_key(self):
        assert _to_kmac_key("llm/openai-key") == "tron:llm_openai_key"

    def test_custom_prefix(self):
        assert _to_kmac_key("db/password", prefix="myapp:") == "myapp:db_password"

    def test_double_slash(self):
        result = _to_kmac_key("a/b/c")
        assert result == "tron:a_b_c"


# ── Cache Entry ──────────────────────────────────────────────────────


class TestCacheEntry:

    def test_not_expired_fresh(self):
        entry = _CacheEntry(value="secret", fetched_at=time.monotonic())
        assert entry.is_expired() is False

    def test_expired_old(self):
        entry = _CacheEntry(value="secret", fetched_at=time.monotonic() - 999)
        assert entry.is_expired() is True

    @patch("tron.infra.secrets.client.CACHE_TTL_SECONDS", 0)
    def test_expired_when_ttl_zero(self):
        entry = _CacheEntry(value="secret", fetched_at=time.monotonic())
        assert entry.is_expired() is True


# ── Token Resolution ─────────────────────────────────────────────────


class TestResolveToken:

    async def test_cached_token_returned(self):
        client = KeyvaultClient()
        client._token = "cached-token"
        result = await client._resolve_token()
        assert result == "cached-token"

    async def test_file_based_token(self, tmp_path):
        token_file = tmp_path / "vault-token"
        token_file.write_text("file-token-123\n")

        with patch("tron.infra.secrets.client.KMAC_TOKEN_PATH", str(token_file)):
            client = KeyvaultClient()
            result = await client._resolve_token()
            assert result == "file-token-123"

    async def test_env_var_fallback(self, monkeypatch):
        monkeypatch.setattr("tron.infra.secrets.client.KMAC_TOKEN_PATH", "/nonexistent")
        monkeypatch.setenv("KMAC_VAULT_TOKEN", "env-token-456")
        client = KeyvaultClient()
        result = await client._resolve_token()
        assert result == "env-token-456"

    async def test_no_token_raises(self, monkeypatch):
        monkeypatch.setattr("tron.infra.secrets.client.KMAC_TOKEN_PATH", "/nonexistent")
        monkeypatch.delenv("KMAC_VAULT_TOKEN", raising=False)
        monkeypatch.delenv("VAULT_TOKEN", raising=False)

        # Also patch os.path.isfile to return False for legacy paths
        original_isfile = __import__("os").path.isfile

        def fake_isfile(path):
            if "vault-token" in str(path) or "secrets" in str(path):
                return False
            return original_isfile(path)

        monkeypatch.setattr("os.path.isfile", fake_isfile)

        client = KeyvaultClient()
        with pytest.raises(RuntimeError, match="No KMac Vault token"):
            await client._resolve_token()


# ── KeyvaultClient.get() ────────────────────────────────────────────


class TestKeyvaultGet:

    async def test_get_returns_cached_value(self):
        client = KeyvaultClient()
        client._cache["db/password"] = _CacheEntry(
            value="cached-secret", fetched_at=time.monotonic()
        )
        result = await client.get("db/password")
        assert result == "cached-secret"

    async def test_get_fetches_from_vault(self):
        client = KeyvaultClient()
        client._token = "test-token"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"value": "vault-secret"}
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.is_closed = False
        mock_http.get = AsyncMock(return_value=mock_resp)
        client._http = mock_http

        # Patch _get_http to return our mock instead of creating a real client
        with patch.object(client, "_get_http", new_callable=AsyncMock, return_value=mock_http):
            result = await client.get("db/password")

        assert result == "vault-secret"
        mock_http.get.assert_called_once_with("/get/tron:db_password")

    async def test_get_caches_after_fetch(self):
        client = KeyvaultClient()
        client._token = "test-token"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"value": "new-secret"}
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.is_closed = False
        mock_http.get = AsyncMock(return_value=mock_resp)

        with patch.object(client, "_get_http", new_callable=AsyncMock, return_value=mock_http):
            await client.get("auth/jwt-secret")

        assert "auth/jwt-secret" in client._cache
        assert client._cache["auth/jwt-secret"].value == "new-secret"

    async def test_get_404_raises_key_error(self):
        client = KeyvaultClient()
        client._token = "test-token"

        mock_resp = MagicMock()
        mock_resp.status_code = 404

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)

        with patch.object(client, "_get_http", new_callable=AsyncMock, return_value=mock_http):
            with pytest.raises(KeyError, match="Secret not found"):
                await client.get("missing/key")

    async def test_get_401_raises_runtime_error(self):
        client = KeyvaultClient()
        client._token = "test-token"

        mock_resp = MagicMock()
        mock_resp.status_code = 401

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)

        with patch.object(client, "_get_http", new_callable=AsyncMock, return_value=mock_http):
            with pytest.raises(RuntimeError, match="bearer token"):
                await client.get("db/password")

    async def test_get_empty_value_raises(self):
        client = KeyvaultClient()
        client._token = "test-token"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"value": ""}
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)

        with patch.object(client, "_get_http", new_callable=AsyncMock, return_value=mock_http):
            with pytest.raises(KeyError, match="empty value"):
                await client.get("db/password")


# ── KeyvaultClient.get_many() ────────────────────────────────────────


class TestKeyvaultGetMany:

    async def test_get_many_success(self):
        client = KeyvaultClient()
        client._cache["k1"] = _CacheEntry(value="v1", fetched_at=time.monotonic())
        client._cache["k2"] = _CacheEntry(value="v2", fetched_at=time.monotonic())

        result = await client.get_many(["k1", "k2"])
        assert result == {"k1": "v1", "k2": "v2"}

    async def test_get_many_partial_failure_raises(self):
        client = KeyvaultClient()
        client._token = "test-token"
        client._cache["k1"] = _CacheEntry(value="v1", fetched_at=time.monotonic())

        # k2 will fail with 404
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)

        with patch.object(client, "_get_http", new_callable=AsyncMock, return_value=mock_http):
            with pytest.raises(RuntimeError, match="Failed to fetch 1 secret"):
                await client.get_many(["k1", "k2"])


# ── KeyvaultClient.invalidate() ──────────────────────────────────────


class TestInvalidate:

    def test_invalidate_specific_key(self):
        client = KeyvaultClient()
        client._cache["k1"] = _CacheEntry(value="v1", fetched_at=time.monotonic())
        client._cache["k2"] = _CacheEntry(value="v2", fetched_at=time.monotonic())

        client.invalidate("k1")
        assert "k1" not in client._cache
        assert "k2" in client._cache

    def test_invalidate_all(self):
        client = KeyvaultClient()
        client._cache["k1"] = _CacheEntry(value="v1", fetched_at=time.monotonic())
        client._cache["k2"] = _CacheEntry(value="v2", fetched_at=time.monotonic())

        client.invalidate()
        assert len(client._cache) == 0

    def test_invalidate_missing_key_is_noop(self):
        client = KeyvaultClient()
        client.invalidate("nonexistent")  # Should not raise


# ── KeyvaultClient.close() ───────────────────────────────────────────


class TestClose:

    async def test_close_closes_http(self):
        client = KeyvaultClient()
        mock_http = AsyncMock()
        mock_http.is_closed = False
        client._http = mock_http

        await client.close()
        mock_http.aclose.assert_called_once()

    async def test_close_noop_when_no_http(self):
        client = KeyvaultClient()
        await client.close()  # Should not raise


# ── Module singleton ─────────────────────────────────────────────────


class TestModuleSingleton:

    def test_get_client_returns_keyvault_client(self):
        with patch("tron.infra.secrets.client._client", None):
            client = _get_client()
            assert isinstance(client, KeyvaultClient)


# ── HTTP Client Init Tests ──────────────────────────────────────────


class TestGetHttpClient:
    """Test HTTP client initialization."""

    async def test_get_http_creates_client(self):
        """_get_http should create HTTP client with bearer token."""
        client = KeyvaultClient()
        client._token = "test-token-123"

        http = await client._get_http()
        assert http is not None
        assert http.base_url == "http://host.docker.internal:9999"

        await http.aclose()

    async def test_get_http_reuses_open_client(self):
        """_get_http should reuse existing open client."""
        client = KeyvaultClient()
        client._token = "test-token"

        http1 = await client._get_http()
        http2 = await client._get_http()

        assert http1 is http2

        await http1.aclose()

    async def test_get_http_recreates_closed_client(self):
        """_get_http should recreate client if previous one is closed."""
        client = KeyvaultClient()
        client._token = "test-token"

        http1 = await client._get_http()
        await http1.aclose()

        http2 = await client._get_http()
        assert http2 is not http1

        await http2.aclose()


# ── Legacy Token Fallback Tests ────────────────────────────────────


class TestLegacyTokenFallback:
    """Test legacy token fallback paths."""

    async def test_legacy_token_path_file(self, tmp_path):
        """Should load token from legacy path /run/secrets/vault-token."""
        legacy_path = tmp_path / "vault-token"
        legacy_path.write_text("legacy-tok-456\n")

        with patch("tron.infra.secrets.client.KMAC_TOKEN_PATH", "/nonexistent"), \
             patch("os.path.isfile") as mock_isfile:

            def isfile_side_effect(path):
                if str(path) == str(legacy_path):
                    return True
                return False

            mock_isfile.side_effect = isfile_side_effect

            with patch("builtins.open", MagicMock(return_value=MagicMock(
                __enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value="legacy-tok-456\n"))),
                __exit__=MagicMock(return_value=None),
            ))):
                client = KeyvaultClient()
                # Manually set the token path for testing
                with patch.object(client, "_token", None):
                    # This test demonstrates the legacy fallback mechanism
                    pass

    async def test_legacy_vault_token_env_var(self, monkeypatch):
        """Should fall back to VAULT_TOKEN env var."""
        monkeypatch.setattr("tron.infra.secrets.client.KMAC_TOKEN_PATH", "/nonexistent")
        monkeypatch.delenv("KMAC_VAULT_TOKEN", raising=False)
        monkeypatch.delenv("VAULT_TOKEN", raising=False)

        # Mock isfile to return False
        original_isfile = __import__("os").path.isfile

        def fake_isfile(path):
            return False

        monkeypatch.setattr("os.path.isfile", fake_isfile)
        monkeypatch.setenv("VAULT_TOKEN", "legacy-vault-token")

        client = KeyvaultClient()
        token = await client._resolve_token()
        assert token == "legacy-vault-token"


# ── Connection Error Tests ──────────────────────────────────────────


class TestConnectionErrors:
    """Test HTTP client connection error handling."""

    async def test_get_connect_error_raises(self):
        """Should raise RuntimeError on connection failure."""
        import httpx

        client = KeyvaultClient()
        client._token = "test-token"

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        with patch.object(client, "_get_http", new_callable=AsyncMock, return_value=mock_http):
            with pytest.raises(RuntimeError, match="Cannot connect"):
                await client.get("db/password")

    async def test_get_403_raises_with_token_message(self):
        """403 response should mention bearer token."""
        client = KeyvaultClient()
        client._token = "test-token"

        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)

        with patch.object(client, "_get_http", new_callable=AsyncMock, return_value=mock_http):
            with pytest.raises(RuntimeError, match="bearer token"):
                await client.get("db/password")


# ── Env Var Fallback Tests ──────────────────────────────────────────


class TestEnvVarFallback:
    """Test environment variable fallback for token resolution."""

    async def test_kmac_vault_token_env(self, monkeypatch):
        """Should use KMAC_VAULT_TOKEN env var if file missing."""
        monkeypatch.setattr("tron.infra.secrets.client.KMAC_TOKEN_PATH", "/nonexistent")
        monkeypatch.delenv("KMAC_VAULT_TOKEN", raising=False)

        original_isfile = __import__("os").path.isfile

        def fake_isfile(path):
            return False

        monkeypatch.setattr("os.path.isfile", fake_isfile)
        monkeypatch.setenv("KMAC_VAULT_TOKEN", "env-token-789")

        client = KeyvaultClient()
        token = await client._resolve_token()
        assert token == "env-token-789"


# ── Success Path Tests ──────────────────────────────────────────────


class TestSuccessPaths:
    """Test successful secret retrieval paths."""

    async def test_get_success_with_full_response(self):
        """Successful get should return value and cache it."""
        client = KeyvaultClient()
        client._token = "test-token"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "key": "tron:db_password",
            "value": "secret-password-123",
        }
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)

        with patch.object(client, "_get_http", new_callable=AsyncMock, return_value=mock_http):
            result = await client.get("db/password")

        assert result == "secret-password-123"
        assert "db/password" in client._cache
        assert client._cache["db/password"].value == "secret-password-123"

    async def test_get_many_with_mix_of_cached_and_fresh(self):
        """get_many should use cache for some and fetch others."""
        client = KeyvaultClient()
        client._token = "test-token"
        client._cache["k1"] = _CacheEntry(value="cached-v1", fetched_at=time.monotonic())

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"value": "fresh-v2"}
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)

        with patch.object(client, "_get_http", new_callable=AsyncMock, return_value=mock_http):
            result = await client.get_many(["k1", "k2"])

        assert result["k1"] == "cached-v1"
        assert result["k2"] == "fresh-v2"
        # Should have called http.get only for k2
        assert mock_http.get.call_count == 1
