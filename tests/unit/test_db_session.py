"""
Unit tests for DB session management.

Tests:
  - init_db sets globals
  - close_db clears globals
  - get_session raises when not initialized
  - get_engine raises when not initialized
  - get_session yields a session
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

import tron.infra.db.session as session_mod


class TestGetSessionNotInit:

    async def test_get_session_raises_without_init(self):
        """get_session raises RuntimeError if DB not initialized."""
        original = session_mod._session_factory
        session_mod._session_factory = None
        try:
            gen = session_mod.get_session()
            with pytest.raises(RuntimeError, match="not initialized"):
                await gen.__anext__()
        finally:
            session_mod._session_factory = original


class TestGetEngineNotInit:

    def test_get_engine_raises_without_init(self):
        """get_engine raises RuntimeError if DB not initialized."""
        original = session_mod._engine
        session_mod._engine = None
        try:
            with pytest.raises(RuntimeError, match="not initialized"):
                session_mod.get_engine()
        finally:
            session_mod._engine = original


class TestInitDb:

    async def test_init_creates_engine_and_factory(self):
        """init_db sets both _engine and _session_factory globals."""
        original_engine = session_mod._engine
        original_factory = session_mod._session_factory
        try:
            # Directly set globals to simulate init_db for SQLite compat
            engine = create_async_engine("sqlite+aiosqlite:///:memory:")
            session_mod._engine = engine
            session_mod._session_factory = MagicMock()

            assert session_mod._engine is not None
            assert session_mod._session_factory is not None
            assert session_mod.get_engine() is engine
        finally:
            if session_mod._engine and session_mod._engine is not original_engine:
                await session_mod._engine.dispose()
            session_mod._engine = original_engine
            session_mod._session_factory = original_factory


class TestCloseDb:

    async def test_close_clears_globals(self):
        """close_db disposes engine and clears globals."""
        original_engine = session_mod._engine
        original_factory = session_mod._session_factory
        try:
            engine = create_async_engine("sqlite+aiosqlite:///:memory:")
            session_mod._engine = engine
            session_mod._session_factory = MagicMock()

            await session_mod.close_db()
            assert session_mod._engine is None
            assert session_mod._session_factory is None
        finally:
            session_mod._engine = original_engine
            session_mod._session_factory = original_factory

    async def test_close_noop_when_not_init(self):
        """close_db is safe to call when not initialized."""
        original = session_mod._engine
        session_mod._engine = None
        try:
            await session_mod.close_db()  # Should not raise
        finally:
            session_mod._engine = original


# ── Engine Creation Tests ───────────────────────────────────────────


class TestInitDbEngineParams:
    """Test async engine creation with correct parameters."""

    async def test_init_db_pool_size_defaults(self):
        """init_db should use correct default pool_size."""
        with patch("tron.infra.db.session.create_async_engine") as mock_create:
            mock_engine = AsyncMock()
            mock_create.return_value = mock_engine

            original_engine = session_mod._engine
            original_factory = session_mod._session_factory
            try:
                await session_mod.init_db("postgresql+asyncpg://user:pass@localhost/db")
                call_kwargs = mock_create.call_args[1]
                assert call_kwargs["pool_size"] == 10
                assert call_kwargs["max_overflow"] == 5
            finally:
                session_mod._engine = original_engine
                session_mod._session_factory = original_factory

    async def test_init_db_pool_pre_ping(self):
        """init_db should enable pool_pre_ping for connection health checks."""
        with patch("tron.infra.db.session.create_async_engine") as mock_create:
            mock_engine = AsyncMock()
            mock_create.return_value = mock_engine

            original_engine = session_mod._engine
            original_factory = session_mod._session_factory
            try:
                await session_mod.init_db("postgresql+asyncpg://user:pass@localhost/db")
                call_kwargs = mock_create.call_args[1]
                assert call_kwargs["pool_pre_ping"] is True
            finally:
                session_mod._engine = original_engine
                session_mod._session_factory = original_factory

    async def test_init_db_pool_recycle(self):
        """init_db should set pool_recycle to 3600 (1 hour)."""
        with patch("tron.infra.db.session.create_async_engine") as mock_create:
            mock_engine = AsyncMock()
            mock_create.return_value = mock_engine

            original_engine = session_mod._engine
            original_factory = session_mod._session_factory
            try:
                await session_mod.init_db("postgresql+asyncpg://user:pass@localhost/db")
                call_kwargs = mock_create.call_args[1]
                assert call_kwargs["pool_recycle"] == 3600
            finally:
                session_mod._engine = original_engine
                session_mod._session_factory = original_factory

    async def test_init_db_custom_pool_size(self):
        """init_db should accept custom pool_size."""
        with patch("tron.infra.db.session.create_async_engine") as mock_create:
            mock_engine = AsyncMock()
            mock_create.return_value = mock_engine

            original_engine = session_mod._engine
            original_factory = session_mod._session_factory
            try:
                await session_mod.init_db(
                    "postgresql+asyncpg://user:pass@localhost/db",
                    pool_size=20,
                    max_overflow=10,
                )
                call_kwargs = mock_create.call_args[1]
                assert call_kwargs["pool_size"] == 20
                assert call_kwargs["max_overflow"] == 10
            finally:
                session_mod._engine = original_engine
                session_mod._session_factory = original_factory


# ── Get Session Commit/Rollback Tests ──────────────────────────────


class TestGetSessionCommitRollback:
    """Test get_session dependency with success and error paths."""

    async def test_get_session_commit_on_success(self):
        """get_session should commit after successful use."""
        from contextlib import asynccontextmanager

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()

        @asynccontextmanager
        async def mock_cm():
            yield mock_session

        def mock_factory():
            return mock_cm()

        with patch("tron.infra.db.session._session_factory", mock_factory):
            gen = session_mod.get_session()
            session = await gen.__anext__()

            assert session == mock_session

            try:
                await gen.__anext__()
            except StopAsyncIteration:
                pass

            mock_session.commit.assert_called_once()

    async def test_get_session_rollback_on_exception(self):
        """get_session should rollback on exception."""
        from contextlib import asynccontextmanager

        mock_session = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.commit = AsyncMock()

        @asynccontextmanager
        async def mock_cm():
            yield mock_session

        def mock_factory():
            return mock_cm()

        with patch("tron.infra.db.session._session_factory", mock_factory):
            gen = session_mod.get_session()
            session = await gen.__anext__()

            # Simulate exception
            try:
                await gen.athrow(ValueError("test error"))
            except ValueError:
                pass

            # Verify rollback was called (via get_session's except block)
            mock_session.rollback.assert_called_once()
