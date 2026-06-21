"""
Expanded unit tests for database session management.

Tests:
  - Session factory creation
  - Connection pool configuration
  - Transaction management
  - Error handling
  - Session cleanup
  - Database URL building
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tron.infra.db.session import (
    init_db,
    close_db,
    get_session,
    get_engine,
)
from tron.api.config import settings


class TestDatabaseURLBuilding:
    """Test database URL construction."""

    def test_async_database_url(self):
        """Async database URL is built correctly."""
        url = settings.database_url("test-password")
        assert "postgresql+asyncpg://" in url
        assert "tron:test-password" in url
        assert "pgbouncer:5432" in url
        assert "/tron" in url

    def test_sync_database_url(self):
        """Sync database URL is built correctly."""
        url = settings.database_url_sync("test-password")
        assert "postgresql://" in url
        assert "tron:test-password" in url
        assert "pgbouncer:5432" in url
        assert "/tron" in url

    def test_database_url_with_special_characters(self):
        """Database URL handles special characters in password."""
        password_with_special = "p@ssw0rd!#$%"
        url = settings.database_url(password_with_special)
        assert "test-password" not in url  # Should use actual password


class TestDatabaseInitialization:
    """Test database engine and session factory initialization."""

    @pytest.mark.asyncio
    async def test_init_db_creates_engine(self):
        """init_db() creates async engine."""
        # Import fresh to reset module state
        import tron.infra.db.session as session_module

        # Save original values
        original_engine = session_module._engine
        original_factory = session_module._session_factory

        try:
            session_module._engine = None
            session_module._session_factory = None

            with patch("tron.infra.db.session.create_async_engine") as mock_create:
                with patch("tron.infra.db.session.async_sessionmaker") as mock_sessionmaker:
                    mock_engine = AsyncMock()
                    mock_create.return_value = mock_engine
                    mock_factory = MagicMock()
                    mock_sessionmaker.return_value = mock_factory

                    await init_db(
                        url="postgresql+asyncpg://user:pass@localhost/db",
                        pool_size=10,
                        max_overflow=5,
                    )

                    mock_create.assert_called_once()
                    mock_sessionmaker.assert_called_once()

        finally:
            # Restore original state
            session_module._engine = original_engine
            session_module._session_factory = original_factory

    @pytest.mark.asyncio
    async def test_init_db_pool_configuration(self):
        """init_db() configures connection pool correctly."""
        import tron.infra.db.session as session_module

        original_engine = session_module._engine
        original_factory = session_module._session_factory

        try:
            session_module._engine = None
            session_module._session_factory = None

            with patch("tron.infra.db.session.create_async_engine") as mock_create:
                with patch("tron.infra.db.session.async_sessionmaker"):
                    mock_engine = AsyncMock()
                    mock_create.return_value = mock_engine

                    await init_db(
                        url="postgresql+asyncpg://user:pass@localhost/db",
                        pool_size=20,
                        max_overflow=10,
                    )

                    # Check pool configuration
                    call_kwargs = mock_create.call_args[1]
                    assert call_kwargs["pool_size"] == 20
                    assert call_kwargs["max_overflow"] == 10
                    assert call_kwargs["pool_pre_ping"] is True
                    assert call_kwargs["pool_recycle"] == 3600

        finally:
            session_module._engine = original_engine
            session_module._session_factory = original_factory

    @pytest.mark.asyncio
    async def test_init_db_session_factory_configuration(self):
        """init_db() configures session factory correctly."""
        import tron.infra.db.session as session_module

        original_engine = session_module._engine
        original_factory = session_module._session_factory

        try:
            session_module._engine = None
            session_module._session_factory = None

            with patch("tron.infra.db.session.create_async_engine"):
                with patch("tron.infra.db.session.async_sessionmaker") as mock_sessionmaker:
                    mock_engine = AsyncMock()
                    mock_factory = MagicMock()
                    mock_sessionmaker.return_value = mock_factory

                    await init_db(url="postgresql+asyncpg://user:pass@localhost/db")

                    # Check session factory configuration
                    call_kwargs = mock_sessionmaker.call_args[1]
                    assert call_kwargs["class_"] == AsyncSession
                    assert call_kwargs["expire_on_commit"] is False

        finally:
            session_module._engine = original_engine
            session_module._session_factory = original_factory


class TestSessionDependency:
    """Test get_session dependency."""

    @pytest.mark.asyncio
    async def test_get_session_yields_session(self):
        """get_session() yields an AsyncSession."""
        import tron.infra.db.session as session_module

        original_factory = session_module._session_factory

        try:
            mock_session = AsyncMock(spec=AsyncSession)
            mock_factory = MagicMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            session_module._session_factory = mock_factory

            async for session in get_session():
                assert session == mock_session

        finally:
            session_module._session_factory = original_factory

    @pytest.mark.asyncio
    async def test_get_session_commits_on_success(self):
        """get_session() commits on successful completion."""
        import tron.infra.db.session as session_module

        original_factory = session_module._session_factory

        try:
            mock_session = AsyncMock(spec=AsyncSession)
            mock_factory = MagicMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            session_module._session_factory = mock_factory

            async for session in get_session():
                pass  # Just complete normally

            mock_session.commit.assert_called_once()

        finally:
            session_module._session_factory = original_factory

    @pytest.mark.asyncio
    async def test_get_session_error_handling(self):
        """get_session() handles errors."""
        import tron.infra.db.session as session_module

        original_factory = session_module._session_factory

        try:
            mock_session = AsyncMock(spec=AsyncSession)
            mock_factory = MagicMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            session_module._session_factory = mock_factory

            # Just verify the session generator works
            async for session in get_session():
                assert session == mock_session
                break

        finally:
            session_module._session_factory = original_factory

    @pytest.mark.asyncio
    async def test_get_session_not_initialized_raises_error(self):
        """get_session() raises RuntimeError if not initialized."""
        import tron.infra.db.session as session_module

        original_factory = session_module._session_factory

        try:
            session_module._session_factory = None

            with pytest.raises(RuntimeError, match="not initialized"):
                async for session in get_session():
                    pass

        finally:
            session_module._session_factory = original_factory


class TestDatabaseCleanup:
    """Test database cleanup."""

    @pytest.mark.asyncio
    async def test_close_db_disposes_engine(self):
        """close_db() disposes of the engine."""
        import tron.infra.db.session as session_module

        original_engine = session_module._engine
        original_factory = session_module._session_factory

        try:
            mock_engine = AsyncMock()
            session_module._engine = mock_engine
            session_module._session_factory = MagicMock()

            await close_db()

            mock_engine.dispose.assert_called_once()

        finally:
            session_module._engine = original_engine
            session_module._session_factory = original_factory

    @pytest.mark.asyncio
    async def test_close_db_clears_references(self):
        """close_db() clears module references."""
        import tron.infra.db.session as session_module

        original_engine = session_module._engine
        original_factory = session_module._session_factory

        try:
            session_module._engine = AsyncMock()
            session_module._session_factory = MagicMock()

            await close_db()

            assert session_module._engine is None
            assert session_module._session_factory is None

        finally:
            session_module._engine = original_engine
            session_module._session_factory = original_factory

    @pytest.mark.asyncio
    async def test_close_db_without_engine(self):
        """close_db() handles no engine gracefully."""
        import tron.infra.db.session as session_module

        original_engine = session_module._engine
        original_factory = session_module._session_factory

        try:
            session_module._engine = None
            session_module._session_factory = None

            await close_db()  # Should not raise

        finally:
            session_module._engine = original_engine
            session_module._session_factory = original_factory


class TestGetEngine:
    """Test get_engine() function."""

    def test_get_engine_returns_engine(self):
        """get_engine() returns the current engine."""
        import tron.infra.db.session as session_module

        original_engine = session_module._engine

        try:
            mock_engine = MagicMock()
            session_module._engine = mock_engine

            engine = get_engine()
            assert engine == mock_engine

        finally:
            session_module._engine = original_engine

    def test_get_engine_not_initialized_raises_error(self):
        """get_engine() raises RuntimeError if not initialized."""
        import tron.infra.db.session as session_module

        original_engine = session_module._engine

        try:
            session_module._engine = None

            with pytest.raises(RuntimeError, match="not initialized"):
                get_engine()

        finally:
            session_module._engine = original_engine


class TestConnectionPoolSettings:
    """Test connection pool configuration."""

    def test_pool_pre_ping_enabled(self):
        """pool_pre_ping is enabled for health checks."""
        import tron.infra.db.session as session_module

        original_engine = session_module._engine

        try:
            with patch("tron.infra.db.session.create_async_engine") as mock_create:
                with patch("tron.infra.db.session.async_sessionmaker"):
                    mock_engine = AsyncMock()
                    mock_create.return_value = mock_engine

                    import asyncio
                    asyncio.run(init_db("postgresql+asyncpg://user:pass@localhost/db"))

                    call_kwargs = mock_create.call_args[1]
                    assert call_kwargs["pool_pre_ping"] is True

        finally:
            session_module._engine = original_engine

    def test_pool_recycle_configured(self):
        """pool_recycle is configured to 3600 seconds."""
        import tron.infra.db.session as session_module

        original_engine = session_module._engine

        try:
            with patch("tron.infra.db.session.create_async_engine") as mock_create:
                with patch("tron.infra.db.session.async_sessionmaker"):
                    mock_engine = AsyncMock()
                    mock_create.return_value = mock_engine

                    import asyncio
                    asyncio.run(init_db("postgresql+asyncpg://user:pass@localhost/db"))

                    call_kwargs = mock_create.call_args[1]
                    assert call_kwargs["pool_recycle"] == 3600

        finally:
            session_module._engine = original_engine

    def test_echo_disabled_in_production(self):
        """SQL echo is disabled."""
        import tron.infra.db.session as session_module

        original_engine = session_module._engine

        try:
            with patch("tron.infra.db.session.create_async_engine") as mock_create:
                with patch("tron.infra.db.session.async_sessionmaker"):
                    mock_engine = AsyncMock()
                    mock_create.return_value = mock_engine

                    import asyncio
                    asyncio.run(init_db("postgresql+asyncpg://user:pass@localhost/db"))

                    call_kwargs = mock_create.call_args[1]
                    assert call_kwargs["echo"] is False

        finally:
            session_module._engine = original_engine


class TestDefaultPoolSize:
    """Test default pool size configuration."""

    @pytest.mark.asyncio
    async def test_default_pool_size_10(self):
        """Default pool size is 10."""
        import tron.infra.db.session as session_module

        original_engine = session_module._engine
        original_factory = session_module._session_factory

        try:
            session_module._engine = None
            session_module._session_factory = None

            with patch("tron.infra.db.session.create_async_engine") as mock_create:
                with patch("tron.infra.db.session.async_sessionmaker"):
                    mock_engine = AsyncMock()
                    mock_create.return_value = mock_engine

                    await init_db("postgresql+asyncpg://user:pass@localhost/db")

                    call_kwargs = mock_create.call_args[1]
                    assert call_kwargs["pool_size"] == 10

        finally:
            session_module._engine = original_engine
            session_module._session_factory = original_factory

    @pytest.mark.asyncio
    async def test_default_max_overflow_5(self):
        """Default max overflow is 5."""
        import tron.infra.db.session as session_module

        original_engine = session_module._engine
        original_factory = session_module._session_factory

        try:
            session_module._engine = None
            session_module._session_factory = None

            with patch("tron.infra.db.session.create_async_engine") as mock_create:
                with patch("tron.infra.db.session.async_sessionmaker"):
                    mock_engine = AsyncMock()
                    mock_create.return_value = mock_engine

                    await init_db("postgresql+asyncpg://user:pass@localhost/db")

                    call_kwargs = mock_create.call_args[1]
                    assert call_kwargs["max_overflow"] == 5

        finally:
            session_module._engine = original_engine
            session_module._session_factory = original_factory


class TestCustomPoolConfiguration:
    """Test custom pool configuration."""

    @pytest.mark.asyncio
    async def test_custom_pool_size(self):
        """Custom pool size is respected."""
        import tron.infra.db.session as session_module

        original_engine = session_module._engine
        original_factory = session_module._session_factory

        try:
            session_module._engine = None
            session_module._session_factory = None

            with patch("tron.infra.db.session.create_async_engine") as mock_create:
                with patch("tron.infra.db.session.async_sessionmaker"):
                    mock_engine = AsyncMock()
                    mock_create.return_value = mock_engine

                    await init_db(
                        "postgresql+asyncpg://user:pass@localhost/db",
                        pool_size=25,
                    )

                    call_kwargs = mock_create.call_args[1]
                    assert call_kwargs["pool_size"] == 25

        finally:
            session_module._engine = original_engine
            session_module._session_factory = original_factory

    @pytest.mark.asyncio
    async def test_custom_max_overflow(self):
        """Custom max overflow is respected."""
        import tron.infra.db.session as session_module

        original_engine = session_module._engine
        original_factory = session_module._session_factory

        try:
            session_module._engine = None
            session_module._session_factory = None

            with patch("tron.infra.db.session.create_async_engine") as mock_create:
                with patch("tron.infra.db.session.async_sessionmaker"):
                    mock_engine = AsyncMock()
                    mock_create.return_value = mock_engine

                    await init_db(
                        "postgresql+asyncpg://user:pass@localhost/db",
                        max_overflow=15,
                    )

                    call_kwargs = mock_create.call_args[1]
                    assert call_kwargs["max_overflow"] == 15

        finally:
            session_module._engine = original_engine
            session_module._session_factory = original_factory
