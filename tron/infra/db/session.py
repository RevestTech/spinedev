"""
Database session management.

Connection URL built at runtime with password from keyvault.
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db(
    url: str,
    pool_size: int = 10,
    max_overflow: int = 5,
) -> None:
    """Initialize the async database engine and session factory."""
    global _engine, _session_factory

    _engine = create_async_engine(
        url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,
        pool_recycle=3600,
        echo=False,
    )
    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    logger.info(
        "Database engine created (pool_size=%d, max_overflow=%d)",
        pool_size,
        max_overflow,
    )


async def close_db() -> None:
    """Close the database engine."""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Database engine closed.")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency: yields an async database session."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_engine() -> AsyncEngine:
    """Get the current engine (for health checks)."""
    if _engine is None:
        raise RuntimeError("Database not initialized.")
    return _engine
