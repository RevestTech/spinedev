"""Run Alembic migrations synchronously (API container startup)."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from alembic import command
from alembic.config import Config

logger = logging.getLogger(__name__)


def _alembic_ini_path() -> Path:
    # tron/infra/db/migrate.py → repo root (WORKDIR /app)
    return Path(__file__).resolve().parents[3] / "alembic.ini"


def run_sync_migrations(database_url_sync: str) -> None:
    """Apply Alembic migrations to head when ``TRON_AUTO_MIGRATE`` is truthy."""
    raw = os.getenv("TRON_AUTO_MIGRATE", "false").lower().strip()
    if raw not in ("1", "true", "yes", "on"):
        logger.info("TRON_AUTO_MIGRATE disabled — skipping Alembic upgrade")
        return

    ini = _alembic_ini_path()
    if not ini.is_file():
        logger.warning("alembic.ini not found at %s — skipping migrations", ini)
        return

    # alembic/env.py prefers DATABASE_URL over ini — set for this process only.
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url_sync
    try:
        cfg = Config(str(ini))
        logger.info("Running Alembic upgrade head…")
        command.upgrade(cfg, "head")
        logger.info("Alembic upgrade head completed")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
