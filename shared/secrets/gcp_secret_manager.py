"""
shared/secrets/gcp_secret_manager.py
====================================

GCP Secret Manager adapter.

Uses `google-cloud-secret-manager`. The SDK exposes both sync and
async clients; we use the sync client for consistency with the AWS
and Azure adapters (one bridging pattern across all three cloud
adapters) and dispatch through `asyncio.to_thread`.

Authentication:
    Defers to Application Default Credentials (ADC). Same #9
    rationale: ADC tokens are auth, not secret payloads.

Path semantics:
    GCP Secret Manager has two layers: the secret (a name) and its
    versions. We always read the "latest" version on get. `path` is
    the *short name* (just the secret id); the project_id is supplied
    at construction time so callers don't have to repeat it.

    Internally we resolve to the fully-qualified resource name
    `projects/{project_id}/secrets/{path}` and (for get) the
    version specifier `/versions/latest`.
"""

from __future__ import annotations

import asyncio
from typing import Any

try:
    from google.api_core import exceptions as gax_exceptions
    from google.cloud import secretmanager
except ImportError:  # pragma: no cover - documented dep
    secretmanager = None  # type: ignore[assignment]
    gax_exceptions = None  # type: ignore[assignment]

from .base import (
    SecretAccessDenied,
    SecretAdapter,
    SecretBackendError,
    SecretNotFound,
)


class GCPSecretManagerAdapter(SecretAdapter):
    """GCP Secret Manager adapter.

    Args:
        project_id: GCP project that owns the secrets.
        client: Optional pre-built `SecretManagerServiceClient` (DI / testing).
    """

    name = "gcp"

    def __init__(
        self,
        project_id: str,
        *,
        client: Any | None = None,
    ) -> None:
        if not project_id:
            raise SecretBackendError(
                "GCPSecretManagerAdapter requires a non-empty project_id"
            )
        self._project_id = project_id
        if client is not None:
            self._client = client
        else:
            if secretmanager is None:
                raise SecretBackendError(
                    "google-cloud-secret-manager is required for "
                    "GCPSecretManagerAdapter; install with "
                    "`pip install google-cloud-secret-manager`"
                )
            self._client = secretmanager.SecretManagerServiceClient()

    # ------------------------------------------------------------------
    # Public adapter contract
    # ------------------------------------------------------------------

    async def get(self, path: str) -> str:
        name = f"projects/{self._project_id}/secrets/{path}/versions/latest"
        response = await self._call(
            self._client.access_secret_version, request={"name": name}
        )
        try:
            data: bytes = response.payload.data
        except AttributeError as exc:
            raise SecretBackendError(
                f"GCP response for {path} missing payload.data"
            ) from exc
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SecretBackendError(
                f"GCP secret at {path} is not valid UTF-8"
            ) from exc

    async def put(self, path: str, value: str) -> None:
        parent = f"projects/{self._project_id}"
        secret_name = f"{parent}/secrets/{path}"
        # Ensure the secret exists; create if absent.
        try:
            await self._call(
                self._client.get_secret, request={"name": secret_name}
            )
        except SecretNotFound:
            await self._call(
                self._client.create_secret,
                request={
                    "parent": parent,
                    "secret_id": path,
                    "secret": {"replication": {"automatic": {}}},
                },
            )
        # Add a new version with the payload.
        await self._call(
            self._client.add_secret_version,
            request={
                "parent": secret_name,
                "payload": {"data": value.encode("utf-8")},
            },
        )

    async def delete(self, path: str) -> None:
        name = f"projects/{self._project_id}/secrets/{path}"
        try:
            await self._call(
                self._client.delete_secret, request={"name": name}
            )
        except SecretNotFound:
            # Idempotent per contract.
            return None

    async def list(self, prefix: str = "") -> list[str]:
        parent = f"projects/{self._project_id}"

        def _collect() -> list[str]:
            names: list[str] = []
            pager = self._client.list_secrets(request={"parent": parent})
            for secret in pager:
                # secret.name is the fully-qualified resource path; strip
                # back to short name for caller convenience.
                full = getattr(secret, "name", "") or ""
                short = full.rsplit("/", 1)[-1]
                if short and (not prefix or short.startswith(prefix)):
                    names.append(short)
            return names

        try:
            return await asyncio.to_thread(_collect)
        except Exception as exc:  # noqa: BLE001
            self._translate_and_raise(exc)
            return []  # pragma: no cover - unreachable

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _call(self, fn: Any, **kwargs: Any) -> Any:
        try:
            return await asyncio.to_thread(fn, **kwargs)
        except Exception as exc:  # noqa: BLE001
            self._translate_and_raise(exc)

    @staticmethod
    def _translate_and_raise(exc: Exception) -> None:
        if gax_exceptions is not None:
            if isinstance(exc, gax_exceptions.NotFound):
                raise SecretNotFound(str(exc)) from exc
            if isinstance(
                exc,
                (
                    gax_exceptions.PermissionDenied,
                    gax_exceptions.Unauthenticated,
                ),
            ):
                raise SecretAccessDenied(str(exc)) from exc
            if isinstance(exc, gax_exceptions.GoogleAPIError):
                raise SecretBackendError(str(exc)) from exc
        raise SecretBackendError(str(exc)) from exc
