"""
shared/secrets/cache.py
=======================

In-process TTL cache that composes around any `SecretAdapter`.

Why a cache lives here at all:
    Vault round-trips on every call would dominate hot paths
    (every LLM call resolves a provider API key; every DB connect
    resolves a DSN). A short default TTL gives big wins for
    repeated reads while still bounding staleness.

Why TTL not LRU:
    LRU would mask rotation events — a rotated secret could remain
    cached indefinitely if it kept getting hit. TTL guarantees
    eventual freshness without explicit invalidation, which is the
    safer default for secrets.

Concurrency model:
    Single asyncio lock per cache instance. A more sophisticated
    per-key lock would prevent thundering-herd on simultaneous miss
    of the same path; we can revisit if the cost ledger flags it.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from .base import SecretAdapter


_DEFAULT_TTL_SECONDS = 60.0


@dataclass
class _Entry:
    value: str
    expires_at: float


class CachedAdapter(SecretAdapter):
    """Wrap another `SecretAdapter` with a TTL read cache.

    Only `get` is cached. `put` invalidates the cached key.
    `delete` invalidates the cached key. `list` is NOT cached (the
    set of paths changes more dynamically than individual values).

    Args:
        inner: The wrapped adapter that actually talks to a backend.
        default_ttl: Seconds before a cached entry is treated as stale.
            60s is conservative — short enough to follow rotations,
            long enough to absorb typical bursts.
    """

    name = "cached"

    def __init__(
        self,
        inner: SecretAdapter,
        *,
        default_ttl: float = _DEFAULT_TTL_SECONDS,
    ) -> None:
        self._inner = inner
        self._default_ttl = default_ttl
        self._entries: dict[str, _Entry] = {}
        self._lock = asyncio.Lock()
        # Expose inner adapter's name so SecretRef round-trips correctly
        # through a cache wrapper.
        self.name = inner.name

    # ------------------------------------------------------------------
    # Public adapter contract
    # ------------------------------------------------------------------

    async def get(self, path: str, ttl: float | None = None) -> str:
        # Note: `ttl` here is a convenience extension beyond the strict
        # SecretAdapter contract. Pure-contract callers pass only path.
        now = time.monotonic()
        async with self._lock:
            entry = self._entries.get(path)
            if entry is not None and entry.expires_at > now:
                return entry.value
        # Miss / stale → fetch outside the lock to avoid holding it
        # during network I/O, then write under lock.
        value = await self._inner.get(path)
        expires = now + (ttl if ttl is not None else self._default_ttl)
        async with self._lock:
            self._entries[path] = _Entry(value=value, expires_at=expires)
        return value

    async def put(self, path: str, value: str) -> None:
        await self._inner.put(path, value)
        async with self._lock:
            self._entries.pop(path, None)

    async def delete(self, path: str) -> None:
        await self._inner.delete(path)
        async with self._lock:
            self._entries.pop(path, None)

    async def list(self, prefix: str = "") -> list[str]:
        return await self._inner.list(prefix)

    async def close(self) -> None:
        await self._inner.close()
        async with self._lock:
            self._entries.clear()

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    async def invalidate(self, path: str | None = None) -> None:
        """Drop one entry, or the whole cache if path is None."""
        async with self._lock:
            if path is None:
                self._entries.clear()
            else:
                self._entries.pop(path, None)

    def stats(self) -> dict[str, int | float]:
        """Cheap visibility hook; no locking — best-effort snapshot."""
        now = time.monotonic()
        live = sum(1 for e in self._entries.values() if e.expires_at > now)
        return {
            "entries_total": len(self._entries),
            "entries_live": live,
            "default_ttl_seconds": self._default_ttl,
        }
