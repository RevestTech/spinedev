"""
Redis client with keyvault-backed password.
"""

from __future__ import annotations

import logging

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_pool: aioredis.Redis | None = None


async def init_redis(url: str, pool_size: int = 50) -> None:
    """Initialize the Redis connection pool."""
    global _pool
    _pool = aioredis.from_url(
        url,
        max_connections=pool_size,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
        retry_on_timeout=True,
    )
    # Verify connection
    await _pool.ping()
    logger.info("Redis connected (pool_size=%d)", pool_size)


async def close_redis() -> None:
    """Close the Redis connection pool."""
    global _pool
    if _pool:
        await _pool.aclose()
        _pool = None
        logger.info("Redis connection closed.")


def get_redis() -> aioredis.Redis:
    """Get the Redis client (for dependency injection)."""
    if _pool is None:
        raise RuntimeError("Redis not initialized. Call init_redis() first.")
    return _pool
