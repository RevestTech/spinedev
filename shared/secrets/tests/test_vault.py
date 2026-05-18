"""
shared/secrets/tests/test_vault.py
==================================

Tests for VaultAdapter against a mocked httpx.AsyncClient. No real
Vault is contacted. Exercises:
    * KV v2 read envelope unwrapping
    * 404 → SecretNotFound; 403 → SecretAccessDenied
    * delete idempotency
    * list path composition
    * namespace header propagation
"""

from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from shared.secrets import (
    SecretAccessDenied,
    SecretBackendError,
    SecretNotFound,
    VaultAdapter,
)


def _build_response(
    status: int,
    body: dict[str, Any] | None = None,
    *,
    text: str = "",
) -> MagicMock:
    """Build a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status
    resp.text = text or (json.dumps(body) if body is not None else "")
    if body is not None:
        resp.json.return_value = body
    else:
        resp.json.side_effect = ValueError("no json")
    return resp


def _build_client(responses: list[MagicMock]) -> MagicMock:
    """Build a mock httpx.AsyncClient that returns scripted responses."""
    client = MagicMock()
    client.request = AsyncMock(side_effect=responses)
    client.aclose = AsyncMock()
    return client


class TestVaultAdapterGet(unittest.TestCase):
    def test_get_unwraps_kv_v2_envelope_value_key(self) -> None:
        body = {"data": {"data": {"value": "s3cret"}, "metadata": {}}}
        client = _build_client([_build_response(200, body)])
        adapter = VaultAdapter(
            url="https://vault.test:8200", token="tkn", client=client
        )
        value = asyncio.run(adapter.get("app/db"))
        self.assertEqual(value, "s3cret")
        # Verify URL composition and header
        args, kwargs = client.request.call_args
        self.assertEqual(args[0], "GET")
        self.assertIn("/v1/secret/data/app/db", args[1])
        self.assertEqual(kwargs["headers"]["X-Vault-Token"], "tkn")

    def test_get_single_key_convenience(self) -> None:
        body = {"data": {"data": {"password": "hunter2"}, "metadata": {}}}
        client = _build_client([_build_response(200, body)])
        adapter = VaultAdapter(
            url="https://vault.test:8200", token="tkn", client=client
        )
        value = asyncio.run(adapter.get("app/db"))
        self.assertEqual(value, "hunter2")

    def test_get_404_raises_not_found(self) -> None:
        client = _build_client([_build_response(404, text="not found")])
        adapter = VaultAdapter(
            url="https://vault.test:8200", token="tkn", client=client
        )
        with self.assertRaises(SecretNotFound):
            asyncio.run(adapter.get("missing"))

    def test_get_403_raises_access_denied(self) -> None:
        client = _build_client([_build_response(403, text="denied")])
        adapter = VaultAdapter(
            url="https://vault.test:8200", token="tkn", client=client
        )
        with self.assertRaises(SecretAccessDenied):
            asyncio.run(adapter.get("forbidden"))

    def test_get_500_then_success_retries(self) -> None:
        success_body = {"data": {"data": {"value": "ok"}, "metadata": {}}}
        client = _build_client(
            [
                _build_response(503, text="overload"),
                _build_response(200, success_body),
            ]
        )
        adapter = VaultAdapter(
            url="https://vault.test:8200", token="tkn", client=client
        )
        value = asyncio.run(adapter.get("flaky"))
        self.assertEqual(value, "ok")
        self.assertEqual(client.request.call_count, 2)


class TestVaultAdapterPut(unittest.TestCase):
    def test_put_sends_kv_v2_envelope(self) -> None:
        client = _build_client([_build_response(200, {"data": {}})])
        adapter = VaultAdapter(
            url="https://vault.test:8200", token="tkn", client=client
        )
        asyncio.run(adapter.put("app/db", "new-secret"))
        _, kwargs = client.request.call_args
        self.assertEqual(kwargs["json"], {"data": {"value": "new-secret"}})


class TestVaultAdapterDelete(unittest.TestCase):
    def test_delete_uses_metadata_path(self) -> None:
        client = _build_client([_build_response(204)])
        adapter = VaultAdapter(
            url="https://vault.test:8200", token="tkn", client=client
        )
        asyncio.run(adapter.delete("app/db"))
        args, _ = client.request.call_args
        self.assertEqual(args[0], "DELETE")
        self.assertIn("/v1/secret/metadata/app/db", args[1])

    def test_delete_swallows_not_found(self) -> None:
        client = _build_client([_build_response(404, text="gone")])
        adapter = VaultAdapter(
            url="https://vault.test:8200", token="tkn", client=client
        )
        # Should NOT raise.
        asyncio.run(adapter.delete("already-gone"))


class TestVaultAdapterList(unittest.TestCase):
    def test_list_composes_absolute_paths(self) -> None:
        body = {"data": {"keys": ["api-key", "db-password"]}}
        client = _build_client([_build_response(200, body)])
        adapter = VaultAdapter(
            url="https://vault.test:8200", token="tkn", client=client
        )
        out = asyncio.run(adapter.list("app"))
        self.assertEqual(out, ["app/api-key", "app/db-password"])

    def test_list_404_returns_empty(self) -> None:
        client = _build_client([_build_response(404, text="no folder")])
        adapter = VaultAdapter(
            url="https://vault.test:8200", token="tkn", client=client
        )
        self.assertEqual(asyncio.run(adapter.list("nowhere")), [])


class TestVaultAdapterNamespace(unittest.TestCase):
    def test_namespace_header_set(self) -> None:
        body = {"data": {"data": {"value": "ns-secret"}, "metadata": {}}}
        client = _build_client([_build_response(200, body)])
        adapter = VaultAdapter(
            url="https://vault.test:8200",
            token="tkn",
            namespace="tenant-a",
            client=client,
        )
        asyncio.run(adapter.get("app/key"))
        _, kwargs = client.request.call_args
        self.assertEqual(kwargs["headers"]["X-Vault-Namespace"], "tenant-a")


class TestVaultAdapterMalformed(unittest.TestCase):
    def test_get_missing_data_raises_backend_error(self) -> None:
        body = {"data": {}}  # no inner "data"
        client = _build_client([_build_response(200, body)])
        adapter = VaultAdapter(
            url="https://vault.test:8200", token="tkn", client=client
        )
        with self.assertRaises(SecretBackendError):
            asyncio.run(adapter.get("malformed"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
