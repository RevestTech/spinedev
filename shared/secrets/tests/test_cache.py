"""
shared/secrets/tests/test_cache.py
==================================

Tests for CachedAdapter — TTL behaviour, invalidation on write/delete,
list pass-through, stats.
"""

from __future__ import annotations

import asyncio
import time
import unittest

from shared.secrets import CachedAdapter, SecretAdapter, SecretNotFound


class _CountingAdapter(SecretAdapter):
    name = "counting"

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.gets = 0
        self.puts = 0
        self.deletes = 0
        self.lists = 0

    async def get(self, path: str) -> str:
        self.gets += 1
        if path not in self.store:
            raise SecretNotFound(path)
        return self.store[path]

    async def put(self, path: str, value: str) -> None:
        self.puts += 1
        self.store[path] = value

    async def delete(self, path: str) -> None:
        self.deletes += 1
        self.store.pop(path, None)

    async def list(self, prefix: str = "") -> list[str]:
        self.lists += 1
        return sorted(k for k in self.store if k.startswith(prefix))


class TestCachedAdapter(unittest.TestCase):
    def test_get_caches(self) -> None:
        inner = _CountingAdapter()
        asyncio.run(inner.put("a", "1"))
        cache = CachedAdapter(inner, default_ttl=60.0)

        v1 = asyncio.run(cache.get("a"))
        v2 = asyncio.run(cache.get("a"))
        self.assertEqual(v1, "1")
        self.assertEqual(v2, "1")
        # Only the initial fetch hits inner (put + the one get).
        self.assertEqual(inner.gets, 1)

    def test_ttl_expiry(self) -> None:
        inner = _CountingAdapter()
        asyncio.run(inner.put("a", "1"))
        # Sub-second TTL so the test stays fast.
        cache = CachedAdapter(inner, default_ttl=0.05)

        asyncio.run(cache.get("a"))
        time.sleep(0.1)
        asyncio.run(cache.get("a"))
        self.assertEqual(inner.gets, 2)

    def test_put_invalidates(self) -> None:
        inner = _CountingAdapter()
        asyncio.run(inner.put("a", "1"))
        cache = CachedAdapter(inner)

        asyncio.run(cache.get("a"))
        asyncio.run(cache.put("a", "2"))
        value = asyncio.run(cache.get("a"))
        self.assertEqual(value, "2")

    def test_delete_invalidates(self) -> None:
        inner = _CountingAdapter()
        asyncio.run(inner.put("a", "1"))
        cache = CachedAdapter(inner)

        asyncio.run(cache.get("a"))
        asyncio.run(cache.delete("a"))
        with self.assertRaises(SecretNotFound):
            asyncio.run(cache.get("a"))

    def test_list_not_cached(self) -> None:
        inner = _CountingAdapter()
        asyncio.run(inner.put("a", "1"))
        cache = CachedAdapter(inner)

        asyncio.run(cache.list("a"))
        asyncio.run(cache.list("a"))
        self.assertEqual(inner.lists, 2)

    def test_invalidate_all(self) -> None:
        inner = _CountingAdapter()
        asyncio.run(inner.put("a", "1"))
        asyncio.run(inner.put("b", "2"))
        cache = CachedAdapter(inner)

        asyncio.run(cache.get("a"))
        asyncio.run(cache.get("b"))
        asyncio.run(cache.invalidate())
        asyncio.run(cache.get("a"))
        asyncio.run(cache.get("b"))
        self.assertEqual(inner.gets, 4)

    def test_per_call_ttl_override(self) -> None:
        inner = _CountingAdapter()
        asyncio.run(inner.put("a", "1"))
        cache = CachedAdapter(inner, default_ttl=60.0)

        # Override with tiny TTL on the first call.
        asyncio.run(cache.get("a", ttl=0.01))
        time.sleep(0.05)
        asyncio.run(cache.get("a"))
        self.assertEqual(inner.gets, 2)

    def test_stats_reports_entries(self) -> None:
        inner = _CountingAdapter()
        asyncio.run(inner.put("a", "1"))
        cache = CachedAdapter(inner)
        asyncio.run(cache.get("a"))

        stats = cache.stats()
        self.assertEqual(stats["entries_total"], 1)
        self.assertEqual(stats["entries_live"], 1)
        self.assertEqual(stats["default_ttl_seconds"], 60.0)

    def test_name_mirrors_inner(self) -> None:
        inner = _CountingAdapter()
        cache = CachedAdapter(inner)
        self.assertEqual(cache.name, "counting")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
