"""
shared/secrets/tests/test_base.py
=================================

Contract tests for `base.py` types and the module-level adapter
selection chain in `__init__.py`. No network I/O; no SDK imports.
"""

from __future__ import annotations

import asyncio
import os
import unittest

from shared.secrets import (
    SecretAccessDenied,
    SecretAdapter,
    SecretBackendError,
    SecretNotFound,
    SecretRef,
    get_default_adapter,
    get_secret,
    set_default_adapter,
)


class _StubAdapter(SecretAdapter):
    name = "stub"

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.calls: list[tuple[str, str]] = []

    async def get(self, path: str) -> str:
        self.calls.append(("get", path))
        if path not in self.store:
            raise SecretNotFound(path)
        return self.store[path]

    async def put(self, path: str, value: str) -> None:
        self.calls.append(("put", path))
        self.store[path] = value

    async def delete(self, path: str) -> None:
        self.calls.append(("delete", path))
        self.store.pop(path, None)

    async def list(self, prefix: str = "") -> list[str]:
        self.calls.append(("list", prefix))
        return sorted(k for k in self.store if k.startswith(prefix))


class TestExceptionHierarchy(unittest.TestCase):
    def test_specific_exceptions_inherit_from_backend_error(self) -> None:
        self.assertTrue(issubclass(SecretNotFound, SecretBackendError))
        self.assertTrue(issubclass(SecretAccessDenied, SecretBackendError))


class TestSecretRef(unittest.TestCase):
    def test_secretref_is_frozen(self) -> None:
        ref = SecretRef(adapter="vault", path="kv/app/db")
        with self.assertRaises((AttributeError, TypeError)):
            ref.adapter = "aws"  # type: ignore[misc]

    def test_secretref_str(self) -> None:
        self.assertEqual(
            str(SecretRef(adapter="vault", path="kv/app/db")),
            "vault://kv/app/db",
        )


class TestAdapterSelection(unittest.TestCase):
    def setUp(self) -> None:
        set_default_adapter(None)
        # Scrub env hint between tests.
        self._saved_env = os.environ.pop("SPINE_SECRETS_ADAPTER", None)

    def tearDown(self) -> None:
        set_default_adapter(None)
        if self._saved_env is not None:
            os.environ["SPINE_SECRETS_ADAPTER"] = self._saved_env
        else:
            os.environ.pop("SPINE_SECRETS_ADAPTER", None)

    def test_no_adapter_raises_backend_error(self) -> None:
        with self.assertRaises(SecretBackendError):
            get_default_adapter()

    def test_env_hint_alone_still_raises(self) -> None:
        os.environ["SPINE_SECRETS_ADAPTER"] = "vault"
        with self.assertRaises(SecretBackendError) as ctx:
            get_default_adapter()
        self.assertIn("vault", str(ctx.exception))

    def test_explicit_default_wins(self) -> None:
        stub = _StubAdapter()
        set_default_adapter(stub)
        self.assertIs(get_default_adapter(), stub)

    def test_module_level_get_secret_uses_default(self) -> None:
        stub = _StubAdapter()
        asyncio.run(stub.put("kv/app/api-key", "swordfish"))
        set_default_adapter(stub)

        value = asyncio.run(get_secret("kv/app/api-key"))
        self.assertEqual(value, "swordfish")

    def test_module_level_get_secret_propagates_not_found(self) -> None:
        stub = _StubAdapter()
        set_default_adapter(stub)
        with self.assertRaises(SecretNotFound):
            asyncio.run(get_secret("kv/missing"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
