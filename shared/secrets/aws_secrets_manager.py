"""
shared/secrets/aws_secrets_manager.py
=====================================

AWS Secrets Manager adapter.

boto3 is synchronous; per the package contract every adapter method
exposes an async interface. We bridge by dispatching the boto3 calls
through `asyncio.to_thread`, which is the documented pattern for
"sync SDK behind async surface."

Authentication:
    Defers entirely to the AWS credential resolution chain (env, shared
    credentials file, IAM role, etc.). The adapter does NOT pull
    secrets out of env vars itself — those env vars are just boto3's
    own auth, not the secret payload, which is what #9 forbids.

Naming:
    `path` maps to `SecretId` (a name or ARN). AWS Secrets Manager has
    no first-class "prefix listing", so `list(prefix)` uses the
    Filters/Name=prefix API and post-filters defensively.
"""

from __future__ import annotations

import asyncio
from typing import Any

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:  # pragma: no cover - documented dep
    boto3 = None  # type: ignore[assignment]
    BotoCoreError = Exception  # type: ignore[assignment,misc]
    ClientError = Exception  # type: ignore[assignment,misc]

from .base import (
    SecretAccessDenied,
    SecretAdapter,
    SecretBackendError,
    SecretNotFound,
)


class AWSSecretsManagerAdapter(SecretAdapter):
    """AWS Secrets Manager adapter.

    Args:
        region_name: AWS region the secrets live in.
        client: Optional pre-built boto3 client (DI / testing).
        **boto3_kwargs: Forwarded to `boto3.client("secretsmanager", ...)`
            for e.g. profile_name, endpoint_url (LocalStack), session.
    """

    name = "aws"

    def __init__(
        self,
        region_name: str | None = None,
        *,
        client: Any | None = None,
        **boto3_kwargs: Any,
    ) -> None:
        if boto3 is None and client is None:
            raise SecretBackendError(
                "boto3 is required for AWSSecretsManagerAdapter; "
                "install with `pip install boto3`"
            )
        if client is not None:
            self._client = client
        else:
            self._client = boto3.client(
                "secretsmanager", region_name=region_name, **boto3_kwargs
            )

    # ------------------------------------------------------------------
    # Public adapter contract
    # ------------------------------------------------------------------

    async def get(self, path: str) -> str:
        response = await self._call(
            self._client.get_secret_value, SecretId=path
        )
        # AWS returns SecretString or SecretBinary; we only expose strings.
        if "SecretString" in response and response["SecretString"] is not None:
            return response["SecretString"]
        if "SecretBinary" in response:
            raise SecretBackendError(
                f"secret at {path} is binary; string-only contract"
            )
        raise SecretBackendError(
            f"AWS response for {path} contained no SecretString"
        )

    async def put(self, path: str, value: str) -> None:
        # Strategy: try update; if NotFound, create.
        try:
            await self._call(
                self._client.put_secret_value,
                SecretId=path,
                SecretString=value,
            )
        except SecretNotFound:
            await self._call(
                self._client.create_secret,
                Name=path,
                SecretString=value,
            )

    async def delete(self, path: str) -> None:
        try:
            await self._call(
                self._client.delete_secret,
                SecretId=path,
                ForceDeleteWithoutRecovery=True,
            )
        except SecretNotFound:
            # Idempotent per contract.
            return None

    async def list(self, prefix: str = "") -> list[str]:
        kwargs: dict[str, Any] = {}
        if prefix:
            kwargs["Filters"] = [{"Key": "name", "Values": [prefix]}]
        out: list[str] = []
        next_token: str | None = None
        while True:
            if next_token:
                kwargs["NextToken"] = next_token
            response = await self._call(self._client.list_secrets, **kwargs)
            for entry in response.get("SecretList", []) or []:
                name = entry.get("Name")
                if name and (not prefix or name.startswith(prefix)):
                    out.append(name)
            next_token = response.get("NextToken")
            if not next_token:
                break
        return out

    # ------------------------------------------------------------------
    # Internals — bridge sync boto3 to async
    # ------------------------------------------------------------------

    async def _call(self, fn: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(fn, **kwargs)
        except ClientError as exc:
            code = (
                exc.response.get("Error", {}).get("Code")
                if hasattr(exc, "response") and isinstance(exc.response, dict)
                else None
            )
            if code in {"ResourceNotFoundException"}:
                raise SecretNotFound(str(exc)) from exc
            if code in {"AccessDeniedException", "UnauthorizedOperation"}:
                raise SecretAccessDenied(str(exc)) from exc
            raise SecretBackendError(str(exc)) from exc
        except BotoCoreError as exc:
            raise SecretBackendError(str(exc)) from exc
