"""
Keyvault client for runtime secret retrieval.

All secrets (API keys, passwords, tokens, signing keys) live in the
centralized KMac Vault. The application NEVER reads secrets from
environment variables or .env files.

KMac Vault API:
    GET  /get/{key}   → {"value": "..."}
    POST /set         → {"key": "...", "value": "..."}
    GET  /list        → ["key1", "key2", ...]

Auth: Bearer token from /vault-token mount or KMAC_VAULT_TOKEN env.

Usage:
    from tron.infra.secrets import get_secret, get_secrets

    # Single secret
    db_password = await get_secret("db/password")

    # Multiple secrets in one call
    secrets = await get_secrets(["llm/openai-key", "llm/anthropic-key"])

The caller uses slash-delimited logical keys (e.g. "db/password").
Internally, we translate to KMac Vault's colon-prefix + underscore
format (e.g. "tron:db_password") so the rest of the codebase is
agnostic to the vault backend.

Secret path convention (caller → KMac key):
    db/password          → tron:db_password
    redis/password       → tron:redis_password
    auth/secret-key      → tron:auth_secret_key
    auth/jwt-secret      → tron:auth_jwt_secret
    auth/master-key      → tron:auth_master_key
    llm/openai-key       → tron:llm_openai_key
    llm/anthropic-key    → tron:llm_anthropic_key
    anthropic-key        → tron:anthropic_key (optional; merged into llm/anthropic-key at worker boot)
    minio/user           → tron:minio_user
    minio/password       → tron:minio_password
    grafana/password     → tron:grafana_password
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

# KMac Vault URL — host.docker.internal from inside Docker, localhost from host
KMAC_VAULT_URL = os.getenv(
    "KMAC_VAULT_URL", "http://host.docker.internal:9999"
)

# Prefix applied to all keys when reading from KMac Vault
KMAC_VAULT_PREFIX = os.getenv("KMAC_VAULT_PREFIX", "tron:")

# Token file path (mounted into container) or env var fallback
KMAC_TOKEN_PATH = os.getenv("KMAC_TOKEN_PATH", "/vault-token")

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
# Key Translation
# ---------------------------------------------------------------------------

def _to_kmac_key(logical_key: str, prefix: str = KMAC_VAULT_PREFIX) -> str:
    """Translate a logical slash-delimited key to KMac Vault format.

    "db/password"      → "tron:db_password"
    "llm/openai-key"   → "tron:llm_openai_key"
    "auth/master-key"  → "tron:auth_master_key"
    """
    # Replace slashes and hyphens with underscores
    normalized = logical_key.replace("/", "_").replace("-", "_")
    return f"{prefix}{normalized}"


# ---------------------------------------------------------------------------
# Keyvault Client
# ---------------------------------------------------------------------------

@dataclass
class KeyvaultClient:
    """
    Async client for reading secrets from KMac Vault.

    Supports:
    - Bearer token auth (reads token from file or env var)
    - In-memory caching with configurable TTL
    - Bulk reads for startup efficiency
    - Transparent key translation (caller uses logical paths,
      client translates to KMac format)
    """

    vault_url: str = KMAC_VAULT_URL
    key_prefix: str = KMAC_VAULT_PREFIX
    _cache: dict[str, _CacheEntry] = field(default_factory=dict)
    _token: str | None = field(default=None, repr=False)
    _http: httpx.AsyncClient | None = field(default=None, repr=False)

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            token = await self._resolve_token()
            self._http = httpx.AsyncClient(
                base_url=self.vault_url,
                timeout=10.0,
                headers={"Authorization": f"Bearer {token}"},
            )
        return self._http

    async def _resolve_token(self) -> str:
        """Resolve KMac Vault bearer token from (in order): cached, file, env var."""
        if self._token:
            return self._token

        # 1. File-based token (preferred — mounted into container)
        if os.path.isfile(KMAC_TOKEN_PATH):
            with open(KMAC_TOKEN_PATH) as f:
                self._token = f.read().strip()
                logger.info("KMac Vault token loaded from %s", KMAC_TOKEN_PATH)
                return self._token

        # 2. Environment variable (development fallback)
        env_token = os.getenv("KMAC_VAULT_TOKEN")
        if env_token:
            self._token = env_token
            logger.warning(
                "KMac Vault token loaded from KMAC_VAULT_TOKEN env var. "
                "Use file-based token mount in production."
            )
            return self._token

        # 3. Legacy fallback — try the old HashiCorp token paths
        for legacy_path in ["/run/secrets/vault-token"]:
            if os.path.isfile(legacy_path):
                with open(legacy_path) as f:
                    self._token = f.read().strip()
                    logger.warning(
                        "Using legacy vault token from %s. "
                        "Migrate to KMac Vault token mount.",
                        legacy_path,
                    )
                    return self._token

        legacy_token = os.getenv("VAULT_TOKEN")
        if legacy_token:
            self._token = legacy_token
            logger.warning(
                "Using legacy VAULT_TOKEN env var as KMac bearer token. "
                "Migrate to KMAC_VAULT_TOKEN."
            )
            return self._token

        raise RuntimeError(
            "No KMac Vault token found. Provide token via:\n"
            f"  1. File mount at {KMAC_TOKEN_PATH}\n"
            "  2. KMAC_VAULT_TOKEN environment variable\n"
            "See VAULT_MIGRATION.md for setup instructions."
        )

    async def get(self, key: str, **_kwargs) -> str:
        """
        Read a single secret from KMac Vault.

        Args:
            key: Logical secret path, e.g. "db/password".
                 Automatically translated to KMac format ("tron:db_password").

        Returns:
            The secret value as a string.

        Raises:
            KeyError: If the secret does not exist in vault.
            RuntimeError: If vault is unreachable or auth fails.
        """
        # Check cache first
        cached = self._cache.get(key)
        if cached and not cached.is_expired():
            return cached.value

        # Translate to KMac key format
        kmac_key = _to_kmac_key(key, self.key_prefix)

        http = await self._get_http()
        try:
            resp = await http.get(f"/get/{kmac_key}")
        except httpx.ConnectError as e:
            raise RuntimeError(
                f"Cannot connect to KMac Vault at {self.vault_url}. "
                f"Is the vault running? Error: {e}"
            ) from e

        if resp.status_code == 401 or resp.status_code == 403:
            raise RuntimeError(
                f"KMac Vault returned {resp.status_code} for key '{kmac_key}'. "
                "Check your bearer token."
            )

        if resp.status_code == 404:
            raise KeyError(
                f"Secret not found in KMac Vault: '{kmac_key}' "
                f"(logical key: '{key}'). "
                f"Add it with: kmac vault set  or  "
                f"curl -X POST {self.vault_url}/set "
                f'-d \'{{"key": "{kmac_key}", "value": "..."}}\''
            )

        resp.raise_for_status()

        data = resp.json()
        value = data.get("value", "")
        if not value:
            raise KeyError(
                f"Secret '{kmac_key}' exists but has empty value."
            )

        # Cache it
        self._cache[key] = _CacheEntry(value=value, fetched_at=time.monotonic())
        logger.debug(
            "Secret '%s' (→ %s) fetched and cached (TTL=%ds)",
            key, kmac_key, CACHE_TTL_SECONDS,
        )
        return value

    async def get_many(self, keys: list[str]) -> dict[str, str]:
        """
        Read multiple secrets concurrently.

        Returns:
            Dict mapping logical key → secret value.
        """
        results = await asyncio.gather(
            *[self.get(k) for k in keys],
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
                f"Failed to fetch {len(errors)} secret(s) from KMac Vault:\n"
                + "\n".join(errors)
            )
        return out

    def invalidate(self, key: str | None = None) -> None:
        """Clear cached secret(s). Pass None to clear all."""
        if key is None:
            self._cache.clear()
        else:
            self._cache.pop(key, None)

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._http and not self._http.is_closed:
            await self._http.aclose()
            self._http = None


# ---------------------------------------------------------------------------
# Module-level singleton & convenience functions
# ---------------------------------------------------------------------------

_client: KeyvaultClient | None = None


def _get_client() -> KeyvaultClient:
    global _client
    if _client is None:
        _client = KeyvaultClient()
    return _client


async def get_secret(key: str) -> str:
    """Module-level convenience: read a single secret from KMac Vault."""
    return await _get_client().get(key)


async def get_secrets(keys: list[str]) -> dict[str, str]:
    """Module-level convenience: read multiple secrets concurrently."""
    return await _get_client().get_many(keys)
