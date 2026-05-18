"""
shared/secrets/azure_keyvault.py
================================

Azure Key Vault adapter.

Uses the official `azure-keyvault-secrets` SDK. The SDK ships both
sync and async clients; we use the sync client and bridge through
`asyncio.to_thread` to keep the dependency surface minimal (the
async client pulls in `aiohttp` indirectly via `azure.core.aio`).

Authentication:
    Defers to `azure.identity.DefaultAzureCredential` (or any
    credential object the caller injects). Same #9 rationale as the
    AWS adapter: credentials are NOT secret values.

Path semantics:
    Azure Key Vault uses flat names — there is no folder hierarchy.
    `path` maps directly to the secret name. `list(prefix)` filters
    in-process because the SDK has no server-side prefix filter.
"""

from __future__ import annotations

import asyncio
from typing import Any

try:
    from azure.core.exceptions import (
        ClientAuthenticationError,
        HttpResponseError,
        ResourceNotFoundError,
    )
    from azure.keyvault.secrets import SecretClient
except ImportError:  # pragma: no cover - documented dep
    SecretClient = None  # type: ignore[assignment,misc]
    ResourceNotFoundError = Exception  # type: ignore[assignment,misc]
    ClientAuthenticationError = Exception  # type: ignore[assignment,misc]
    HttpResponseError = Exception  # type: ignore[assignment,misc]

from .base import (
    SecretAccessDenied,
    SecretAdapter,
    SecretBackendError,
    SecretNotFound,
)


class AzureKeyVaultAdapter(SecretAdapter):
    """Azure Key Vault adapter.

    Args:
        vault_url: Full vault URL, e.g. "https://my-kv.vault.azure.net".
        credential: An azure-identity credential. If not supplied, the
            caller is responsible for either using `client=` or
            constructing `DefaultAzureCredential()` themselves.
        client: Optional pre-built `SecretClient` (DI / testing).
    """

    name = "azure"

    def __init__(
        self,
        vault_url: str | None = None,
        credential: Any | None = None,
        *,
        client: Any | None = None,
    ) -> None:
        if client is not None:
            self._client = client
            return
        if SecretClient is None:
            raise SecretBackendError(
                "azure-keyvault-secrets is required for AzureKeyVaultAdapter; "
                "install with `pip install azure-keyvault-secrets azure-identity`"
            )
        if vault_url is None or credential is None:
            raise SecretBackendError(
                "AzureKeyVaultAdapter requires either client= or "
                "(vault_url= AND credential=)"
            )
        self._client = SecretClient(vault_url=vault_url, credential=credential)

    # ------------------------------------------------------------------
    # Public adapter contract
    # ------------------------------------------------------------------

    async def get(self, path: str) -> str:
        secret = await self._call(self._client.get_secret, path)
        value = getattr(secret, "value", None)
        if value is None:
            raise SecretBackendError(
                f"Azure Key Vault returned no value for {path}"
            )
        if not isinstance(value, str):
            raise SecretBackendError(
                f"Azure Key Vault value for {path} is not a string"
            )
        return value

    async def put(self, path: str, value: str) -> None:
        await self._call(self._client.set_secret, path, value)

    async def delete(self, path: str) -> None:
        try:
            poller = await self._call(self._client.begin_delete_secret, path)
        except SecretNotFound:
            # Idempotent per contract.
            return None
        # The poller is sync; await its result in a thread too.
        await asyncio.to_thread(poller.result)

    async def list(self, prefix: str = "") -> list[str]:
        # list_properties_of_secrets returns an iterable; consume in a thread.
        def _collect() -> list[str]:
            names: list[str] = []
            for props in self._client.list_properties_of_secrets():
                name = getattr(props, "name", None)
                if name and (not prefix or name.startswith(prefix)):
                    names.append(name)
            return names

        try:
            return await asyncio.to_thread(_collect)
        except ResourceNotFoundError as exc:
            # Vault itself missing; surface as backend error not NotFound.
            raise SecretBackendError(str(exc)) from exc
        except ClientAuthenticationError as exc:
            raise SecretAccessDenied(str(exc)) from exc
        except HttpResponseError as exc:
            raise SecretBackendError(str(exc)) from exc

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _call(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except ResourceNotFoundError as exc:
            raise SecretNotFound(str(exc)) from exc
        except ClientAuthenticationError as exc:
            raise SecretAccessDenied(str(exc)) from exc
        except HttpResponseError as exc:
            status = getattr(exc, "status_code", None)
            if status in (401, 403):
                raise SecretAccessDenied(str(exc)) from exc
            if status == 404:
                raise SecretNotFound(str(exc)) from exc
            raise SecretBackendError(str(exc)) from exc
