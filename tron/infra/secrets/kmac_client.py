"""
KMac Vault client adapter for Tron.

Provides the same interface as KeyvaultClient but connects to KMac Vault
(central secrets management system) instead of HashiCorp Vault.

KMac Vault API:
    Base URL: http://host.docker.internal:9999 (from Docker) or http://127.0.0.1:9999 (from host)
    Auth: Bearer token from ~/.config/kmac/docker-vault-token
    Secrets: Stored with "tron:" prefix (e.g., "tron:db_password")

Usage:
    from tron.infra.secrets.kmac_client import KMacVaultClient

    client = KMacVaultClient()
    db_password = await client.get("db_password")  # Auto-prefixed to "tron:db_password"
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

KMAC_VAULT_URL = os.getenv("KMAC_VAULT_URL", "http://host.docker.internal:9999")
KMAC_TOKEN_PATH = os.getenv("KMAC_TOKEN_PATH", "/vault-token")
KMAC_SECRET_PREFIX = os.getenv("KMAC_SECRET_PREFIX", "tron:")

# Cache TTL — secrets are cached in memory to avoid per-request vault calls.
# Default 5 minutes. Set to 0 to disable caching.
CACHE_TTL_SECONDS = int(os.getenv("VAULT_CACHE_TTL", "300"))


# ---------------------------------------------------------------------------
# Cached secret entry
# ---------------------------------------------------------------------------

@dataclass
class _CacheEntry:
    value: str
    fetched_at: float

    def is_expired(self) -> bool:
        if CACHE_TTL_SECONDS <= 0:
            return True
        return (time.monotonic() - self.fetched_at) > CACHE_TTL_SECONDS


# ---------------------------------------------------------------------------
# KMac Vault Client
# ---------------------------------------------------------------------------

@dataclass
class KMacVaultClient:
    """
    Async client for reading secrets from KMac Vault.

    Provides the same interface as KeyvaultClient for drop-in replacement.

    Supports:
    - Bearer token auth (reads from KMAC_TOKEN_PATH or KMAC_TOKEN env)
    - In-memory caching with configurable TTL
    - Bulk reads for startup efficiency
    - Graceful error handling with clear messages
    """

    vault_url: str = KMAC_VAULT_URL
    secret_prefix: str = KMAC_SECRET_PREFIX
    _cache: dict[str, _CacheEntry] = field(default_factory=dict)
    _token: str | None = field(default=None, repr=False)
    _http: httpx.AsyncClient | None = field(default=None, repr=False)

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                base_url=self.vault_url,
                timeout=10.0,
                headers={"Authorization": f"Bearer {await self._resolve_token()}"},
            )
        return self._http

    async def _resolve_token(self) -> str:
        """Resolve KMac vault token from (in order): cached, file, env var."""
        if self._token:
            return self._token

        # 1. File-based token (preferred — injected by orchestrator)
        if os.path.isfile(KMAC_TOKEN_PATH):
            with open(KMAC_TOKEN_PATH) as f:
                self._token = f.read().strip()
                logger.info("KMac vault token loaded from %s", KMAC_TOKEN_PATH)
                return self._token

        # 2. Environment variable (development fallback)
        env_token = os.getenv("KMAC_TOKEN")
        if env_token:
            self._token = env_token
            logger.warning(
                "KMac vault token loaded from KMAC_TOKEN env var. "
                "Use file-based token injection in production."
            )
            return self._token

        raise RuntimeError(
            "No KMac vault token found. Provide token via file at "
            f"{KMAC_TOKEN_PATH} or KMAC_TOKEN env var."
        )

    def _full_key(self, key: str) -> str:
        """Build the full vault key with prefix (e.g., "tron:db_password")."""
        # KMac vault expects keys with prefix
        # If key already has prefix, don't add it again
        if key.startswith(self.secret_prefix):
            return key
        # Normalize key: replace slashes and hyphens with underscores (KMac naming convention)
        # e.g., "auth/secret-key" → "tron:auth_secret_key"
        key_normalized = key.replace("/", "_").replace("-", "_")
        return f"{self.secret_prefix}{key_normalized}"

    async def get(self, key: str, *, field_name: str = "value") -> str:
        """
        Read a single secret from KMac vault.

        Args:
            key: Secret path relative to prefix, e.g. "db/password" or "auth/secret-key" 
                 → "tron:db_password" or "tron:auth_secret_key"
            field_name: Ignored (KMac returns simple {"key": "...", "value": "..."})

        Returns:
            The secret value as a string.

        Raises:
            KeyError: If the secret does not exist in vault.
            RuntimeError: If vault is unreachable or auth fails.
        """
        # Normalize key to cache key (replace slashes and hyphens with underscores)
        cache_key = key.replace("/", "_").replace("-", "_")
        
        # Check cache
        cached = self._cache.get(cache_key)
        if cached and not cached.is_expired():
            return cached.value

        # Fetch from KMac vault
        http = await self._get_http()
        full_key = self._full_key(key)
        path = f"/get/{full_key}"

        try:
            resp = await http.get(path)
        except httpx.ConnectError as e:
            raise RuntimeError(
                f"Cannot connect to KMac vault at {self.vault_url}. "
                f"Is the kmac-vault container running? Error: {e}"
            ) from e

        if resp.status_code == 401:
            raise RuntimeError(
                f"KMac vault returned 401 Unauthorized for {full_key}. "
                "Check token validity."
            )

        if resp.status_code == 404:
            raise KeyError(
                f"Secret not found in KMac vault: {full_key}. "
                f"Use 'kmac vault set' to add it or check the key name."
            )

        resp.raise_for_status()

        data = resp.json()
        try:
            value = data["value"]
        except (KeyError, TypeError) as e:
            raise KeyError(
                f"Secret {full_key} exists but 'value' field not found. "
                f"Response: {data}"
            ) from e

        # Cache it
        self._cache[cache_key] = _CacheEntry(value=value, fetched_at=time.monotonic())
        logger.debug("Secret '%s' fetched from KMac vault and cached (TTL=%ds)", full_key, CACHE_TTL_SECONDS)
        return value

    async def get_many(self, keys: list[str], *, field_name: str = "value") -> dict[str, str]:
        """
        Read multiple secrets concurrently from KMac vault.

        Returns:
            Dict mapping key → secret value.
        """
        results = await asyncio.gather(
            *[self.get(k, field_name=field_name) for k in keys],
            return_exceptions=True,
        )
        out: dict[str, str] = {}
        errors: list[str] = []
        for key, result in zip(keys, results):
            if isinstance(result, Exception):
                errors.append(f"  {key}: {result}")
            else:
                out[key] = result

        if errors:
            raise RuntimeError(
                f"Failed to fetch {len(errors)} secret(s) from KMac vault:\n"
                + "\n".join(errors)
            )
        return out

    def invalidate(self, key: str | None = None) -> None:
        """Clear cached secret(s). Pass None to clear all."""
        if key is None:
            self._cache.clear()
        else:
            # Normalize key before lookup (replace slashes and hyphens)
            normalized = key.replace("/", "_").replace("-", "_")
            self._cache.pop(normalized, None)

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._http and not self._http.is_closed:
            await self._http.aclose()
            self._http = None


# ---------------------------------------------------------------------------
# Module-level singleton & convenience functions
# ---------------------------------------------------------------------------

_client: KMacVaultClient | None = None


def _get_client() -> KMacVaultClient:
    global _client
    if _client is None:
        _client = KMacVaultClient()
    return _client


async def get_secret(key: str, *, field_name: str = "value") -> str:
    """Module-level convenience: read a single secret from KMac vault."""
    return await _get_client().get(key, field_name=field_name)


async def get_secrets(keys: list[str], *, field_name: str = "value") -> dict[str, str]:
    """Module-level convenience: read multiple secrets concurrently."""
    return await _get_client().get_many(keys, field_name=field_name)
