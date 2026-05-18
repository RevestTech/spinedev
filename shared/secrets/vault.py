"""
shared/secrets/vault.py
=======================

OpenBao / HashiCorp Vault adapter — the Day-0 default per Spine v3
design decision #9.

Targets Vault HTTP API v1 against a KV v2 mount. KV v2 is assumed
because (a) it is the OpenBao default and (b) it is what the wizard
provisions; teams that need KV v1 should fork this adapter rather
than make it conditional, since the path scheme differs.

Auth model:
    Token-based. The token is supplied at construction time (most
    commonly read from a wrapped Kubernetes / AppRole / OIDC login
    by the bootstrap code that constructs the adapter). The adapter
    itself never reads the token from an environment variable in
    its constructor — the CALLER is responsible for sourcing the
    token via whatever mechanism the deployment shape mandates.

Namespace support:
    Optional `namespace` argument maps to the `X-Vault-Namespace`
    HTTP header. OpenBao + Vault Enterprise both honour this.

Path semantics for KV v2:
    Reads/writes hit `/v1/{mount}/data/{path}`.
    Lists hit `/v1/{mount}/metadata/{path}?list=true`.
    Deletes hit `/v1/{mount}/metadata/{path}` (DELETE removes ALL
    versions; this is the conservative "really gone" semantic the
    abstract contract implies — soft-delete-current-version is
    intentionally not the default).

Retry:
    A simple retry policy is built in for transient network errors
    and 5xx responses (3 attempts, exponential backoff 0.2s/0.4s/0.8s).
    The retry surface is intentionally minimal — callers that need
    sophisticated retry should compose `shared/secrets/cache.py` or
    wait for the dedicated retry helper in `shared/runtime/` (Wave 1).
"""

from __future__ import annotations

import asyncio
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover - documented dep, see README
    httpx = None  # type: ignore[assignment]

from .base import (
    SecretAccessDenied,
    SecretAdapter,
    SecretBackendError,
    SecretNotFound,
)


_DEFAULT_TIMEOUT_SECONDS = 10.0
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF_BASE_SECONDS = 0.2


class VaultAdapter(SecretAdapter):
    """HashiCorp Vault / OpenBao adapter targeting KV v2.

    Args:
        url: Base URL of the Vault server, e.g. "https://vault.spine.local:8200".
        token: Vault token. Caller-sourced; see module docstring.
        mount: KV v2 mount name (default "secret" — Vault dev-mode default
            AND the OpenBao wizard default).
        namespace: Optional Vault Enterprise / OpenBao namespace.
        timeout: HTTP timeout in seconds.
        client: Optional pre-built httpx.AsyncClient (for testing / DI).
    """

    name = "vault"

    def __init__(
        self,
        url: str,
        token: str,
        *,
        mount: str = "secret",
        namespace: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
        client: "httpx.AsyncClient | None" = None,
    ) -> None:
        if httpx is None and client is None:
            raise SecretBackendError(
                "httpx is required for VaultAdapter; "
                "install with `pip install httpx`"
            )
        self._url = url.rstrip("/")
        self._token = token
        self._mount = mount.strip("/")
        self._namespace = namespace
        self._timeout = timeout
        self._owned_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)

    # ------------------------------------------------------------------
    # Public adapter contract
    # ------------------------------------------------------------------

    async def get(self, path: str) -> str:
        url = self._kv_data_url(path)
        body = await self._request("GET", url)
        # KV v2 envelope: {"data": {"data": {"value": "..."}, "metadata": {...}}}
        try:
            inner = body["data"]["data"]
        except (KeyError, TypeError) as exc:
            raise SecretBackendError(
                f"malformed KV v2 response at {path}: missing data.data"
            ) from exc
        if not isinstance(inner, dict):
            raise SecretBackendError(
                f"malformed KV v2 response at {path}: data.data is not a dict"
            )
        if "value" in inner:
            value = inner["value"]
        elif len(inner) == 1:
            # Single-key convenience: return the only value
            value = next(iter(inner.values()))
        else:
            raise SecretBackendError(
                f"secret at {path} stores multiple keys "
                f"({sorted(inner)}); use a dedicated reader"
            )
        if not isinstance(value, str):
            raise SecretBackendError(
                f"secret at {path} is not a string (got {type(value).__name__})"
            )
        return value

    async def put(self, path: str, value: str) -> None:
        url = self._kv_data_url(path)
        # KV v2 write envelope: {"data": {"value": "..."}}
        await self._request("POST", url, json={"data": {"value": value}})

    async def delete(self, path: str) -> None:
        url = self._kv_metadata_url(path)
        try:
            await self._request("DELETE", url)
        except SecretNotFound:
            # Per contract, deletion is idempotent.
            return None

    async def list(self, prefix: str = "") -> list[str]:
        url = self._kv_metadata_url(prefix) + "?list=true"
        try:
            body = await self._request("GET", url)
        except SecretNotFound:
            return []
        try:
            keys = body["data"]["keys"]
        except (KeyError, TypeError) as exc:
            raise SecretBackendError(
                f"malformed list response for prefix={prefix!r}"
            ) from exc
        if not isinstance(keys, list):
            raise SecretBackendError(
                f"list response for prefix={prefix!r} did not return a list"
            )
        # Compose absolute paths so callers can feed results back to get().
        prefix_clean = prefix.strip("/")
        if prefix_clean:
            return [f"{prefix_clean}/{k.rstrip('/')}" for k in keys]
        return [k.rstrip("/") for k in keys]

    async def close(self) -> None:
        if self._owned_client:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _kv_data_url(self, path: str) -> str:
        path_clean = path.strip("/")
        return f"{self._url}/v1/{self._mount}/data/{path_clean}"

    def _kv_metadata_url(self, path: str) -> str:
        path_clean = path.strip("/")
        return f"{self._url}/v1/{self._mount}/metadata/{path_clean}"

    def _headers(self) -> dict[str, str]:
        headers = {"X-Vault-Token": self._token}
        if self._namespace:
            headers["X-Vault-Namespace"] = self._namespace
        return headers

    async def _request(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(_RETRY_ATTEMPTS):
            try:
                response = await self._client.request(
                    method, url, headers=self._headers(), json=json
                )
            except Exception as exc:  # noqa: BLE001 - httpx network class is broad
                last_exc = exc
                await self._sleep_backoff(attempt)
                continue

            status = response.status_code
            # 204 No Content (PUT/DELETE success) → empty body is fine.
            if status == 204 or method == "DELETE" and 200 <= status < 300:
                return {}
            if 200 <= status < 300:
                try:
                    return response.json()
                except ValueError as exc:
                    raise SecretBackendError(
                        f"vault returned non-JSON body for {method} {url}"
                    ) from exc
            if status == 404:
                raise SecretNotFound(
                    f"no secret at {url} (vault returned 404)"
                )
            if status in (401, 403):
                raise SecretAccessDenied(
                    f"vault denied {method} {url} (status={status})"
                )
            if 500 <= status < 600 and attempt < _RETRY_ATTEMPTS - 1:
                await self._sleep_backoff(attempt)
                last_exc = SecretBackendError(
                    f"vault {status} on {method} {url}"
                )
                continue
            # Final attempt or 4xx that is not 401/403/404 — surface
            try:
                detail = response.text
            except Exception:  # pragma: no cover
                detail = "<unreadable>"
            raise SecretBackendError(
                f"vault error {status} on {method} {url}: {detail[:200]}"
            )
        # Exhausted retries on transport errors.
        raise SecretBackendError(
            f"vault unreachable after {_RETRY_ATTEMPTS} attempts: {last_exc}"
        ) from last_exc

    @staticmethod
    async def _sleep_backoff(attempt: int) -> None:
        await asyncio.sleep(_RETRY_BACKOFF_BASE_SECONDS * (2 ** attempt))
