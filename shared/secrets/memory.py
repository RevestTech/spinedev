"""
shared.secrets.memory
=====================

In-memory `SecretAdapter` for **testing and bootstrap-only** scenarios.

This adapter holds secrets in process memory (a plain dict). It is the
ONLY adapter that does not require an external vault, and per design
decision #9 it MUST NOT be used in production:

- No persistence — process restart loses all secrets.
- No access control — anyone with adapter reference can read.
- No audit trail — reads/writes are not logged.

Permitted uses:

1. **Unit tests** — pre-populate known values, assert downstream behavior.
2. **Smoke tests** — bootstrap a working approval/HMAC flow without
   spinning up a real Vault/OpenBao container.
3. **Day-0 bootstrap wizard transient state** — staging values briefly
   before writing them to a real adapter; instance discarded immediately.

Any production code path that constructs `InMemoryAdapter` is a bug
that should be caught in code review. The class name is intentionally
verbose to make grep-audits trivial.
"""

from __future__ import annotations

from .base import SecretAdapter, SecretNotFound


class InMemoryAdapter(SecretAdapter):
    """Dict-backed `SecretAdapter`. Test + bootstrap use only."""

    name = "memory"

    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self._store: dict[str, str] = dict(initial or {})

    async def get(self, path: str) -> str:
        try:
            return self._store[path]
        except KeyError as e:
            raise SecretNotFound(path) from e

    async def put(self, path: str, value: str) -> None:
        self._store[path] = value

    async def delete(self, path: str) -> None:
        self._store.pop(path, None)

    async def list(self, prefix: str = "") -> list[str]:
        return sorted(k for k in self._store if k.startswith(prefix))
