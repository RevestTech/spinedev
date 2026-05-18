"""
shared/secrets/base.py
======================

Abstract contract for secret backends.

Per Spine v3 design decision #9 (Vault-only secrets), every code path that
needs a secret MUST route through a `SecretAdapter` implementation. The
public API of this package (`get_secret` / `put_secret` / `delete_secret` /
`list_secrets`) is a thin wrapper around a process-wide default adapter.

Hard rules:
    1. Secret VALUES never come from environment variables. The adapter
       configuration itself (e.g. a Vault token) may be sourced from env,
       but the secret payload always comes from a vault-class backend.
    2. All adapter methods are async to keep the call surface uniform
       across HTTP-backed (Vault) and SDK-backed (boto3/azure/gcp)
       implementations.
    3. Adapters are responsible for translating their backend-specific
       errors into the three canonical exceptions defined here so
       callers can write provider-agnostic error handling.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Canonical exception hierarchy
# ---------------------------------------------------------------------------


class SecretBackendError(Exception):
    """Generic backend failure (network, 5xx, malformed response, etc.)."""


class SecretNotFound(SecretBackendError):
    """Raised when the requested path does not exist in the backend."""


class SecretAccessDenied(SecretBackendError):
    """Raised when the caller is authenticated but lacks permission.

    Distinct from auth-failure: a missing/expired token is also surfaced
    as SecretAccessDenied so the caller can re-auth via the same handler.
    """


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SecretRef:
    """A typed pointer to a secret in a specific backend.

    Stored in bundles, schemas, manifests — anywhere a secret VALUE
    would otherwise leak into config. Resolution happens at use time
    via the configured default adapter (or a named adapter registry,
    once that lands in Wave 1).
    """

    adapter: str  # "vault" | "aws" | "azure" | "gcp"
    path: str     # adapter-relative path

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.adapter}://{self.path}"


# ---------------------------------------------------------------------------
# Adapter contract
# ---------------------------------------------------------------------------


class SecretAdapter(ABC):
    """Abstract base for every secret backend.

    All implementations MUST be async. Sync SDKs (boto3, azure SDK,
    google-cloud-secret-manager) are bridged via `asyncio.to_thread`
    inside the concrete adapter — do NOT expose blocking calls.
    """

    #: Short adapter identifier ("vault" / "aws" / "azure" / "gcp").
    #: Used by SecretRef and registry lookups; subclasses override.
    name: str = "abstract"

    @abstractmethod
    async def get(self, path: str) -> str:
        """Fetch the secret VALUE stored at `path`.

        Raises:
            SecretNotFound: path does not exist
            SecretAccessDenied: insufficient permission or bad/expired auth
            SecretBackendError: transport / parse / 5xx
        """

    @abstractmethod
    async def put(self, path: str, value: str) -> None:
        """Store `value` at `path`, creating or overwriting.

        Raises: same hierarchy as `get`.
        """

    @abstractmethod
    async def delete(self, path: str) -> None:
        """Delete the secret at `path`.

        Implementations should treat "already absent" as a no-op
        (return cleanly, do not raise SecretNotFound). This keeps
        deletion idempotent for cleanup paths.

        Raises: SecretAccessDenied, SecretBackendError.
        """

    @abstractmethod
    async def list(self, prefix: str = "") -> list[str]:
        """List secret paths starting with `prefix`.

        Returns: list of absolute paths (NOT values). Empty list if
        prefix matches nothing.

        Raises: SecretAccessDenied, SecretBackendError.
        """

    async def close(self) -> None:
        """Release any underlying connections / clients.

        Default no-op; HTTP-backed adapters override to close their
        httpx.AsyncClient. Safe to call multiple times.
        """
        return None
