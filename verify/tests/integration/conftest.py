"""
Integration test conftest — shared SQLite DB factory.

Handles PostgreSQL → SQLite type compatibility:
  - UUID(as_uuid=True) → String(36) via TypeDecorator
  - JSONB → JSON
  - ARRAY → JSON

Key insight: SQLAlchemy's mapper caches type processors on first use.
If unit tests import models before type patches, the mapper's cached
identity-key processor (from PG_UUID) will use uuid.hex (no hyphens).
We must ensure INSERT and SELECT both use the same UUID format.

The approach:
1. Still patch column types for DDL (CREATE TABLE) to work on SQLite
2. Use sqlite3.register_adapter to ensure the sqlite3 driver handles
   uuid.UUID objects consistently (as .hex, matching PG_UUID's cached
   bind processor for non-PG dialects)
3. Use sqlite3.register_converter to read UUIDs back correctly
"""

from __future__ import annotations

import sqlite3
import uuid

import pytest
from sqlalchemy import String, JSON, event, TypeDecorator
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB, ARRAY
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tron.domain.models import ApiKey, Project, AuditRun, Finding, FindingSuppression
from tron.infra.db.base import Base

# Register sqlite3 adapter to convert uuid.UUID → hex string (no hyphens).
# This matches what SQLAlchemy's PG_UUID.process_bind_param returns for
# non-PostgreSQL dialects, ensuring INSERT and SELECT use the same format.
sqlite3.register_adapter(uuid.UUID, lambda u: u.hex)


class SQLiteUUID(TypeDecorator):
    """Store Python uuid.UUID as a 32-char hex string in SQLite.

    Uses .hex (no hyphens) to match what SQLAlchemy's compiled mapper
    identity-key processor expects when the original column type is PG_UUID.
    """

    impl = String(32)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return value.hex if isinstance(value, uuid.UUID) else value
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return uuid.UUID(value) if not isinstance(value, uuid.UUID) else value
        return value


# Tables we need for integration tests (skip PG-only tables like project_cost_limits)
SQLITE_SAFE_TABLES = [
    Project.__table__,
    AuditRun.__table__,
    Finding.__table__,
    FindingSuppression.__table__,
    ApiKey.__table__,
]


_PG_TYPE_ORIGINALS: list = []
_PG_TYPES_PATCHED = False


def _patch_pg_types_for_sqlite():
    """
    Walk SQLITE_SAFE_TABLES and swap any PG-only column types
    to SQLite-compatible equivalents.  This mutates the Table objects
    in-place so create_all emits valid DDL.

    We store originals so we can restore them after the test session.
    Idempotent — safe to call multiple times in one pytest session.
    """
    global _PG_TYPES_PATCHED, _PG_TYPE_ORIGINALS

    if _PG_TYPES_PATCHED:
        return _PG_TYPE_ORIGINALS

    originals = []
    for table in SQLITE_SAFE_TABLES:
        for col in table.columns:
            original_type = col.type
            if isinstance(original_type, PG_UUID):
                originals.append((col, original_type))
                col.type = SQLiteUUID()
            elif isinstance(original_type, JSONB):
                originals.append((col, original_type))
                col.type = JSON()
            elif isinstance(original_type, ARRAY):
                originals.append((col, original_type))
                col.type = JSON()

    _PG_TYPE_ORIGINALS = originals
    _PG_TYPES_PATCHED = True
    return originals


def _restore_pg_types(originals):
    """Restore original PG column types after test session."""
    global _PG_TYPES_PATCHED
    for col, original_type in originals:
        col.type = original_type
    _PG_TYPES_PATCHED = False


@pytest.fixture
async def sqlite_db():
    """
    In-memory SQLite async engine with PG type patches.

    Yields an async_sessionmaker; callers use it to create sessions.
    PG column types are patched before create_all and restored after.
    """
    originals = _patch_pg_types_for_sqlite()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragmas(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")  # OFF: skip FK checks on missing tables
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn, tables=SQLITE_SAFE_TABLES,
            )
        )

    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False,
    )

    try:
        yield factory
    finally:
        await engine.dispose()
        _restore_pg_types(originals)
