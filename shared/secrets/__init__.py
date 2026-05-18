"""
shared.secrets
==============

Vault-only secrets package for Spine v3.

Per design decision #9 (`docs/V3_DESIGN_DECISIONS.md`), every Spine code
path that needs a secret VALUE must route through this package. There is
no fallback to environment variables; there is no built-in secret store;
Spine never holds customer secrets in its own process memory longer than
the TTL cache here permits.

Public surface (locked in Wave 0):

    get_secret(path)        — read
    put_secret(path, value) — write
    delete_secret(path)     — delete (idempotent)
    list_secrets(prefix)    — enumerate
    set_default_adapter(a)  — process-wide default
    get_default_adapter()   — introspect

    SecretAdapter, SecretRef                 — types
    SecretNotFound, SecretAccessDenied,
    SecretBackendError                       — exceptions

    VaultAdapter, AWSSecretsManagerAdapter,
    AzureKeyVaultAdapter,
    GCPSecretManagerAdapter, CachedAdapter   — concrete adapters

Adapter selection chain (when `get_secret` is called with no explicit
adapter context):

    1. An adapter set via `set_default_adapter(...)` — preferred. The
       wizard / Hub bootstrap is expected to call this exactly once
       during startup with a fully-configured adapter (typically a
       `CachedAdapter` wrapping a `VaultAdapter`).
    2. If unset, the ADAPTER NAME may be read from environment variable
       `SPINE_SECRETS_ADAPTER` to give CLI tooling a Day-0 escape hatch.
       This name is the ADAPTER TYPE (e.g. "vault"), NOT a secret value;
       it does NOT violate #9. The adapter must still be constructed and
       registered separately.
    3. Otherwise: raise `SecretBackendError` with a message pointing
       the operator at the wizard.

Hard rules (enforced by tests in Wave 1's validation agent):
    * `shared/secrets/` must contain the ONLY `os.environ.get(...)` calls
      in the codebase that touch secret values — and those calls inside
      this package only read ADAPTER METADATA, never secret payloads.
    * Every public function is async.
    * Every backend error surfaces as one of the three canonical
      exceptions in `base.py`.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from .aws_secrets_manager import AWSSecretsManagerAdapter
from .azure_keyvault import AzureKeyVaultAdapter
from .base import (
    SecretAccessDenied,
    SecretAdapter,
    SecretBackendError,
    SecretNotFound,
    SecretRef,
)
from .cache import CachedAdapter
from .gcp_secret_manager import GCPSecretManagerAdapter
from .memory import InMemoryAdapter
from .vault import VaultAdapter

if TYPE_CHECKING:  # pragma: no cover - typing only
    pass


__all__ = [
    # Public functions
    "get_secret",
    "put_secret",
    "delete_secret",
    "list_secrets",
    "set_default_adapter",
    "get_default_adapter",
    # Types
    "SecretAdapter",
    "SecretRef",
    # Exceptions
    "SecretNotFound",
    "SecretAccessDenied",
    "SecretBackendError",
    # Concrete adapters
    "VaultAdapter",
    "AWSSecretsManagerAdapter",
    "AzureKeyVaultAdapter",
    "GCPSecretManagerAdapter",
    "CachedAdapter",
    "InMemoryAdapter",
]


# ---------------------------------------------------------------------------
# Default adapter management
# ---------------------------------------------------------------------------


_DEFAULT_ADAPTER: SecretAdapter | None = None

# Recognised adapter names for the env-hint chain. Adding a new adapter
# requires both adding a class above AND extending this set.
_KNOWN_ADAPTER_NAMES = frozenset({"vault", "aws", "azure", "gcp"})


def set_default_adapter(adapter: SecretAdapter | None) -> None:
    """Install (or clear) the process-wide default adapter.

    Pass `None` to clear — primarily for tests. Production code should
    set this once during bootstrap.
    """
    global _DEFAULT_ADAPTER
    _DEFAULT_ADAPTER = adapter


def get_default_adapter() -> SecretAdapter:
    """Return the currently-configured default adapter.

    Resolution order:
        1. Adapter installed via `set_default_adapter`.
        2. Adapter NAME hint from `SPINE_SECRETS_ADAPTER` env var. If the
           name is recognised but no adapter has been registered, this
           still raises — the env var is a discovery hint, not an
           auto-constructor (we can't infer Vault URL + token from env).
        3. Raise `SecretBackendError`.
    """
    if _DEFAULT_ADAPTER is not None:
        return _DEFAULT_ADAPTER
    hinted = os.environ.get("SPINE_SECRETS_ADAPTER", "").strip().lower()
    if hinted and hinted in _KNOWN_ADAPTER_NAMES:
        raise SecretBackendError(
            f"SPINE_SECRETS_ADAPTER={hinted} requested but no adapter has "
            "been registered. Call shared.secrets.set_default_adapter() "
            "in your wizard / bootstrap before any secret access."
        )
    raise SecretBackendError(
        "no adapter configured; call shared.secrets.set_default_adapter() "
        "in your wizard / bootstrap before any secret access. "
        "Per decision #9, Spine does not fall back to environment-variable "
        "secret values."
    )


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


async def get_secret(path: str) -> str:
    """Fetch a secret value from the default adapter."""
    return await get_default_adapter().get(path)


async def put_secret(path: str, value: str) -> None:
    """Write a secret value through the default adapter."""
    await get_default_adapter().put(path, value)


async def delete_secret(path: str) -> None:
    """Delete a secret through the default adapter (idempotent)."""
    await get_default_adapter().delete(path)


async def list_secrets(prefix: str = "") -> list[str]:
    """List secret paths through the default adapter."""
    return await get_default_adapter().list(prefix)
