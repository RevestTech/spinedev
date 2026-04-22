"""
Alembic migration environment.

Reads database password from keyvault (or VAULT_TOKEN env for local dev).
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, engine_from_config
from sqlalchemy.engine import Connection

from tron.infra.db.base import Base
from tron.domain.models import (  # noqa: F401 — import all models so metadata is populated
    Project, AuditRun, Finding, LLMUsage, LLMCostHourly, LLMCostDaily,
    ProjectCostLimit, CostEvent, CodeFile, FileDependency,
    FindingRelationship, Standard,
)

# Alembic Config object
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_database_url() -> str:
    """
    Build database URL for migrations.

    For migrations, we use a sync driver (psycopg2) since Alembic
    runs in a sync context. Password comes from:
    1. DATABASE_URL env var (if set directly for migration convenience)
    2. Individual DB_* env vars with DB_PASSWORD
    """
    url = os.getenv("DATABASE_URL")
    if url:
        # Ensure it's a sync URL
        return url.replace("postgresql+asyncpg://", "postgresql://")

    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME", "tron")
    user = os.getenv("DB_USER", "tron")
    password = os.getenv("DB_PASSWORD", "")

    return f"postgresql://{user}:{password}@{host}:{port}/{name}"


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — generates SQL script."""
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode with sync engine."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata
        )
        
        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
