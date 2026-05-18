"""Tests for ``shared.secrets.rotation.rotate()`` — OP3 Wave 3.5 cleanup.

Verifies that the in-band ``rotate()`` entry point:

* Returns a UTC timestamp.
* Delegates to the active adapter's ``rotate(path)`` method if present.
* Fires registered ``RotationHook`` callbacks.
* Attempts to write a ``vault_rotated`` audit row (best-effort, silenced
  when the DB / psql is unavailable as in test envs).
* Reraises adapter failures so the API handler can return 502.
"""

from __future__ import annotations

import asyncio
import unittest
from datetime import datetime

import shared.secrets.rotation as rotation
from shared.secrets import set_default_adapter


class _RotatingAdapter:
    """Duck-typed adapter stub that records every ``rotate()`` call.

    The rotator looks up ``adapter.rotate`` via ``getattr``, so we don't
    need to inherit ``SecretAdapter`` (which would force implementing
    get/put/delete/list — irrelevant for this test).
    """

    name = "rotating-stub"

    def __init__(self) -> None:
        self.rotations: list[str] = []

    async def rotate(self, path: str) -> None:
        self.rotations.append(path)


class _FailingAdapter:
    name = "failing-stub"

    async def rotate(self, path: str) -> None:
        raise RuntimeError("vault unreachable")


class RotateTest(unittest.TestCase):

    def setUp(self) -> None:
        # Reset shared module state so a previous test's adapter doesn't leak.
        set_default_adapter(None)
        rotation.default_rotation_hook.callbacks.clear()

    def tearDown(self) -> None:
        set_default_adapter(None)
        rotation.default_rotation_hook.callbacks.clear()

    def test_rotate_returns_timestamp_with_no_adapter(self) -> None:
        """With no adapter installed, rotate() is a no-op + still timestamps."""
        result = asyncio.run(rotation.rotate("spine/integrations/github/token"))
        self.assertIsInstance(result, datetime)
        # tzinfo present (UTC) so callers can serialize unambiguously
        self.assertIsNotNone(result.tzinfo)

    def test_rotate_calls_adapter_rotate(self) -> None:
        adapter = _RotatingAdapter()
        set_default_adapter(adapter)
        asyncio.run(rotation.rotate("spine/aws/db_root"))
        self.assertEqual(adapter.rotations, ["spine/aws/db_root"])

    def test_rotate_fires_registered_hooks(self) -> None:
        adapter = _RotatingAdapter()
        set_default_adapter(adapter)

        observed: list[str] = []

        async def _listener(path: str) -> None:
            observed.append(path)

        rotation.default_rotation_hook.register("spine/x", _listener)
        asyncio.run(rotation.rotate("spine/x"))
        self.assertEqual(observed, ["spine/x"])

    def test_rotate_reraises_adapter_failure(self) -> None:
        set_default_adapter(_FailingAdapter())
        with self.assertRaises(RuntimeError):
            asyncio.run(rotation.rotate("spine/will/fail"))

    def test_emit_vault_rotated_audit_swallows_db_unavailable(self) -> None:
        """When SPINE_DB_URL is absent, audit emit returns None (not raise)."""
        # Best-effort path: with no DB url and no psql side effects, the
        # helper returns None silently so the rotation continues uninterrupted.
        out = rotation._emit_vault_rotated_audit(
            path="spine/test/path", actor="unit-test"
        )
        # Either None (no DB) or some event_id if a DB happens to be wired —
        # both are valid; the contract is "do not raise".
        self.assertTrue(out is None or isinstance(out, int))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
