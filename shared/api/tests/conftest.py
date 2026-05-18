"""Shared fixtures for ``shared.api.tests``.

Two main fixtures:

* ``oidc_user`` — installs a mock ``KeycloakClient`` that returns a
  deterministic ``TokenClaims`` for ``Bearer test-token``, so any route
  that depends on ``current_user`` is exercised end-to-end without
  network IO.
* ``mock_db_pool`` — installs a tiny asyncpg-shaped object that records
  every query and returns scripted rows. Routes that ``Depends(get_db_pool)``
  see the legacy ``DbHandle`` shape over this mock.

Note: the ``shared/secrets/`` vs stdlib ``secrets`` shadow fix lives in
the repo-root ``conftest.py`` so every test suite inherits it.
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest

from shared.api.dependencies import set_db_pool
from shared.identity.middleware import set_keycloak_client
from shared.identity.models import TokenClaims


# ---------------------------------------------------------------------------
# Identity / Keycloak mock
# ---------------------------------------------------------------------------


class _MockKeycloak:
    """Minimal stand-in for ``KeycloakClient`` — verify_token is async."""

    def __init__(self, *, roles: list[str] | None = None, sub: str = "u-1") -> None:
        self._claims = TokenClaims(
            sub=sub,
            email=f"{sub}@spine.test",
            preferred_username=sub,
            name=sub.title(),
            realm_access={"roles": roles or ["user"]},
            scope="openid profile email",
            exp=9_999_999_999,
            iat=1,
        )

    async def verify_token(self, token: str) -> TokenClaims:
        return self._claims


@pytest.fixture
def oidc_user() -> Iterator[None]:
    """Install a ``user``-roled mock Keycloak client."""
    set_keycloak_client(_MockKeycloak(roles=["user"]))  # type: ignore[arg-type]
    try:
        yield
    finally:
        set_keycloak_client(None)


@pytest.fixture
def oidc_hub_admin() -> Iterator[None]:
    """Install a Keycloak mock granting ``hub-admin``."""
    set_keycloak_client(_MockKeycloak(roles=["hub-admin", "user"]))  # type: ignore[arg-type]
    try:
        yield
    finally:
        set_keycloak_client(None)


# ---------------------------------------------------------------------------
# asyncpg pool mock
# ---------------------------------------------------------------------------


class _MockRecord(dict):
    """Subset of asyncpg ``Record`` we use — dict-like + ``.values()``."""

    def values(self) -> list[Any]:  # type: ignore[override]
        return list(super().values())


class _MockConn:
    """Records every query; replays scripted rows from the parent pool."""

    def __init__(self, pool: "_MockPool") -> None:
        self._pool = pool

    async def fetch(self, sql: str, *args: Any) -> list[_MockRecord]:
        self._pool.queries.append(sql)
        return self._pool.next_rows()

    async def fetchval(self, sql: str, *args: Any) -> Any:
        self._pool.queries.append(sql)
        rows = self._pool.next_rows()
        if not rows:
            return None
        return next(iter(rows[0].values()))

    async def execute(self, sql: str, *args: Any) -> str:
        self._pool.queries.append(sql)
        return "OK"


class _AcquireCtx:
    """Async context manager wrapping a single connection."""

    def __init__(self, pool: "_MockPool") -> None:
        self._pool = pool

    async def __aenter__(self) -> _MockConn:
        return _MockConn(self._pool)

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _MockPool:
    """Tiny asyncpg pool — only ``acquire()`` + a scripted-row queue."""

    def __init__(self) -> None:
        self.queries: list[str] = []
        self._scripts: list[list[_MockRecord]] = []

    def script(self, rows: list[dict[str, Any]]) -> None:
        """Add one scripted result to the FIFO queue."""
        self._scripts.append([_MockRecord(r) for r in rows])

    def next_rows(self) -> list[_MockRecord]:
        if not self._scripts:
            return [_MockRecord({"_row": "1"})]
        return self._scripts.pop(0)

    def acquire(self) -> _AcquireCtx:
        return _AcquireCtx(self)

    async def close(self) -> None:
        return None


@pytest.fixture
def mock_db_pool() -> Iterator[_MockPool]:
    """Install a fresh mock asyncpg pool for the duration of the test."""
    pool = _MockPool()
    set_db_pool(pool)
    try:
        yield pool
    finally:
        set_db_pool(None)
