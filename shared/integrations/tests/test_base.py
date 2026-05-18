"""Tests for ``shared.integrations.base`` — the IntegrationAdapter contract.

Covers the cross-cutting machinery that every per-vendor adapter
inherits from:

* ``IntegrationKind`` enum exposes the 6 documented categories.
* ``TestConnectionResult`` is the uniform probe envelope.
* ``BaseIntegrationAdapter._vault_probe`` is healthy iff the vault path
  resolves to a non-empty secret.
* ``register_adapter`` / ``get_adapter`` / ``known_adapters`` form a
  working in-memory registry.
* ``fetch_secret`` degrades gracefully when ``shared.secrets`` is absent
  or the entry is missing.
"""

from __future__ import annotations

import asyncio

import pytest

from shared.integrations.base import (
    BaseIntegrationAdapter,
    IntegrationKind,
    TestConnectionResult,
    fetch_secret,
    fetch_secret_sync,
    get_adapter,
    known_adapters,
    register_adapter,
)


# ---------------------------------------------------------------------------
# IntegrationKind enum
# ---------------------------------------------------------------------------


def test_integration_kind_has_all_six_categories() -> None:
    """Mirror the catalogue used by the MCP tool + SPA panel."""
    values = {k.value for k in IntegrationKind}
    assert values == {
        "scm", "issue_tracker", "comms", "incident", "voice", "grc",
    }


def test_integration_kind_is_string_valued_for_serialisation() -> None:
    """String values so the MCP envelope + bundle JSON don't need imports."""
    assert IntegrationKind.SCM.value == "scm"
    assert str(IntegrationKind.GRC.value) == "grc"


# ---------------------------------------------------------------------------
# TestConnectionResult
# ---------------------------------------------------------------------------


def test_test_connection_result_minimal_construction() -> None:
    """Name + healthy + probe_mode are required; everything else has a default."""
    r = TestConnectionResult(name="github", healthy=True, probe_mode="real")
    assert r.name == "github"
    assert r.healthy is True
    assert r.probe_mode == "real"
    assert r.detail == ""
    assert r.vault_path is None
    assert r.error is None
    assert r.metadata == {}


def test_test_connection_result_is_frozen() -> None:
    """Frozen dataclass — adapters must build a new result, not mutate."""
    r = TestConnectionResult(name="github", healthy=True, probe_mode="real")
    with pytest.raises(Exception):
        r.healthy = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# BaseIntegrationAdapter._vault_probe
# ---------------------------------------------------------------------------


def test_base_adapter_no_vault_path_returns_stub_healthy() -> None:
    """No vault_path → nothing to probe → return a clean stub envelope."""
    adapter = BaseIntegrationAdapter(name="x", kind=IntegrationKind.SCM)
    res = asyncio.run(adapter.test_connection())
    assert res.name == "x"
    assert res.healthy is True
    assert res.probe_mode == "stub"
    assert "nothing to probe" in res.detail


def test_base_adapter_with_present_vault_path_is_healthy(monkeypatch) -> None:
    """Vault returns a value → adapter reports healthy + records vault_path."""
    import shared.integrations.base as base

    async def _fake(path: str) -> str:
        return "secret-value"

    monkeypatch.setattr(base, "fetch_secret", _fake, raising=True)

    adapter = BaseIntegrationAdapter(
        name="y", kind=IntegrationKind.SCM, vault_path="spine/y/token",
    )
    res = asyncio.run(adapter.test_connection())
    assert res.healthy is True
    assert res.vault_path == "spine/y/token"
    assert "present" in res.detail


def test_base_adapter_with_missing_vault_returns_error(monkeypatch) -> None:
    """Vault returns None → adapter reports unhealthy with vault_secret_missing."""
    import shared.integrations.base as base

    async def _fake(path: str) -> None:
        return None

    monkeypatch.setattr(base, "fetch_secret", _fake, raising=True)

    adapter = BaseIntegrationAdapter(
        name="z", kind=IntegrationKind.GRC, vault_path="evidence/z/api_key",
    )
    res = asyncio.run(adapter.test_connection())
    assert res.healthy is False
    assert res.error == "vault_secret_missing"
    assert res.vault_path == "evidence/z/api_key"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_known_adapters_includes_the_five_v1_adapters() -> None:
    """Importing shared.integrations registers all 5 per-vendor adapters."""
    import shared.integrations  # noqa: F401  (forces registration)

    names = set(known_adapters())
    assert {"twilio", "teams", "pagerduty", "github", "linear"} <= names


def test_register_adapter_is_idempotent_last_write_wins() -> None:
    """Re-registering replaces the prior factory (per V3 KG last-writer)."""
    calls = {"n": 0}

    async def _f1() -> BaseIntegrationAdapter:
        calls["n"] = 1
        return BaseIntegrationAdapter(name="__test", kind=IntegrationKind.SCM)

    async def _f2() -> BaseIntegrationAdapter:
        calls["n"] = 2
        return BaseIntegrationAdapter(name="__test", kind=IntegrationKind.SCM)

    register_adapter("__test", _f1)
    register_adapter("__test", _f2)
    asyncio.run(get_adapter("__test"))
    assert calls["n"] == 2


def test_get_adapter_unknown_name_returns_none() -> None:
    res = asyncio.run(get_adapter("definitely-not-registered"))
    assert res is None


# ---------------------------------------------------------------------------
# fetch_secret degradation behaviour
# ---------------------------------------------------------------------------


def test_fetch_secret_missing_entry_returns_none(monkeypatch) -> None:
    """SecretNotFound from the backend surfaces as None."""
    import shared.integrations.base as base

    class _SecretNotFound(Exception):
        pass

    class _SecretBackendError(Exception):
        pass

    async def _raises(path: str) -> str:
        raise _SecretNotFound(path)

    fake_module = type(
        "M", (),
        {
            "SecretNotFound": _SecretNotFound,
            "SecretBackendError": _SecretBackendError,
            "get_secret": _raises,
        },
    )

    monkeypatch.setitem(
        __import__("sys").modules, "shared.secrets", fake_module,
    )
    res = asyncio.run(base.fetch_secret("nope"))
    assert res is None


def test_fetch_secret_sync_inside_running_loop_returns_none() -> None:
    """Inside a running event loop, sync wrapper returns None (no nested run)."""
    async def _inner() -> object:
        return fetch_secret_sync("any/path")

    res = asyncio.run(_inner())
    assert res is None
