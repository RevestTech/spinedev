"""Tests for ``shared.api.dependencies`` (Wave 3 rebuild).

Covers the asyncpg pool plumbing — init/close, the legacy ``DbHandle``
shim's ``[{"_row": ...}]`` contract, raw row variant, and pool-not-init
errors. Does NOT spin up a real Postgres; the conftest's mock pool is
asyncpg-shaped (acquire → conn.fetch / fetchval).

These tests use ``asyncio.run()`` rather than ``pytest.mark.asyncio``
because ``pytest-asyncio`` is not in the runtime requirements (only
``pytest`` itself is).
"""

from __future__ import annotations

import asyncio

import pytest

from shared.api.dependencies import (
    DbPoolNotInitialized,
    actor_label,
    get_db_pool,
    get_db_pool_raw,
    init_db_pool,
    set_db_pool,
)
from shared.identity.models import TokenClaims, User


# ---------------------------------------------------------------------------
# Pool plumbing
# ---------------------------------------------------------------------------


def test_pool_not_initialized_raises() -> None:
    """``get_db_pool_raw`` must raise when no pool is set."""
    set_db_pool(None)
    with pytest.raises(DbPoolNotInitialized):
        get_db_pool_raw()


def test_init_db_pool_uses_explicit_dsn_no_vault(monkeypatch) -> None:
    """When a DSN is passed explicitly, vault must NOT be consulted."""
    calls: list[str] = []
    set_db_pool(None)

    class _FakePool:
        async def close(self) -> None:
            return None

    async def _fake_create_pool(**kwargs):
        calls.append(kwargs["dsn"])
        return _FakePool()

    import shared.api.dependencies as deps

    monkeypatch.setattr(deps.asyncpg, "create_pool", _fake_create_pool, raising=True)
    try:
        asyncio.run(init_db_pool(dsn="postgresql://x:y@h:5432/d"))
        assert calls == ["postgresql://x:y@h:5432/d"]
        assert get_db_pool_raw() is not None
    finally:
        set_db_pool(None)


def test_init_db_pool_calls_vault_when_dsn_omitted(monkeypatch) -> None:
    """When DSN is omitted, the vault fetcher must be called."""
    set_db_pool(None)

    class _FakePool:
        async def close(self) -> None:
            return None

    async def _fake_create_pool(**kwargs):
        return _FakePool()

    import shared.api.dependencies as deps

    monkeypatch.setattr(deps.asyncpg, "create_pool", _fake_create_pool, raising=True)
    seen: list[str] = []

    async def _fake_secret(path: str) -> str:
        seen.append(path)
        return "postgresql://vault-dsn"

    try:
        asyncio.run(init_db_pool(secret_fetcher=_fake_secret))
        assert seen == [deps.DSN_VAULT_PATH]
    finally:
        set_db_pool(None)


# ---------------------------------------------------------------------------
# DbHandle.fetch legacy contract
# ---------------------------------------------------------------------------


def test_db_handle_fetch_legacy_row_contract(mock_db_pool) -> None:
    """Single-column SELECT must return ``[{"_row": "<text>"}]`` (legacy psql shape)."""
    mock_db_pool.script([{"out": "alpha"}, {"out": "beta"}])
    db = get_db_pool()
    rows = asyncio.run(db.fetch("SELECT 'alpha' UNION ALL SELECT 'beta';"))
    assert rows == [{"_row": "alpha"}, {"_row": "beta"}]


def test_db_handle_fetch_multi_column_joins_with_tab(mock_db_pool) -> None:
    """Multi-column rows are joined with tabs (matches psql ``-At -F<tab>``)."""
    mock_db_pool.script([{"a": "x", "b": "y"}])
    rows = asyncio.run(get_db_pool().fetch("SELECT 'x' AS a, 'y' AS b;"))
    assert rows == [{"_row": "x\ty"}]


def test_db_handle_fetch_rows_returns_native(mock_db_pool) -> None:
    """``fetch_rows`` returns proper dict rows for new routes."""
    mock_db_pool.script([{"id": 1, "name": "alpha"}])
    rows = asyncio.run(get_db_pool().fetch_rows("SELECT 1;"))
    assert rows == [{"id": 1, "name": "alpha"}]


def test_db_handle_ping_true_when_select1_returns_1(mock_db_pool) -> None:
    """``ping`` should call ``SELECT 1;`` via fetchval and return True on 1."""
    mock_db_pool.script([{"_": 1}])
    assert asyncio.run(get_db_pool().ping()) is True
    assert any("SELECT 1" in q for q in mock_db_pool.queries)


def test_db_handle_ping_false_when_pool_uninitialized() -> None:
    """``ping`` swallows DbPoolNotInitialized and returns False."""
    set_db_pool(None)
    assert asyncio.run(get_db_pool().ping()) is False


# ---------------------------------------------------------------------------
# actor_label helper
# ---------------------------------------------------------------------------


def test_actor_label_prefers_username_then_email_then_sub() -> None:
    """``actor_label`` falls back through username → email → sub."""
    base = TokenClaims(sub="sub-xyz", exp=9_999_999_999, iat=1)
    u = User(id=base.sub, raw_claims=base)
    assert actor_label(u) == "sub-xyz"
    u2 = User(id=base.sub, email="a@b.com", raw_claims=base)
    assert actor_label(u2) == "a@b.com"
    u3 = User(id=base.sub, email="a@b.com", username="alice", raw_claims=base)
    assert actor_label(u3) == "alice"
