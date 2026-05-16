"""
Health check endpoints.

/health  — liveness probe (is the process alive?)
/ready   — readiness probe (can it serve traffic? DB + Redis connected?)
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter
from sqlalchemy import text

from tron.infra.db.session import get_engine
from tron.infra.redis.client import get_redis

logger = logging.getLogger(__name__)
router = APIRouter()

_start_time = time.time()


@router.get("/health")
async def health():
    """Liveness probe — process is alive."""
    return {
        "status": "ok",
        "service": "tron-api",
        "uptime_seconds": round(time.time() - _start_time, 1),
    }


@router.get("/ready")
async def ready():
    """Readiness probe — all dependencies connected."""
    checks = {}

    # Database
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            result.scalar()
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"
        logger.warning("Readiness check: database failed — %s", e)

    # Redis
    try:
        redis = get_redis()
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"
        logger.warning("Readiness check: redis failed — %s", e)

    all_ok = all(v == "ok" for v in checks.values())
    status_code = 200 if all_ok else 503

    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if all_ok else "not_ready",
            "checks": checks,
        },
    )
