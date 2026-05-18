"""
federation.hub_registry
=======================

Hub registry — async CRUD over ``spine_federation.hub`` (V23 migration).

Per #10 the local Hub knows about three classes of peer:

* its own identity (`hub_id`, read at bootstrap from the file the Day-0
  wizard writes — `hub/_state/hub_id.txt`),
* its `parent_hub` (zero or one — root Hubs have none),
* its `children` (zero or many — leaf Hubs have none).

This module is the *only* writer to `spine_federation.hub`. The Wave 3
REST routes in `shared/api/routes/federation.py` currently keep an
in-process graph; once this module is wired into the Hub lifespan, those
routes call through here and the in-process graph is replaced.

Bootstrap contract (cross-subsystem):

    hub/wizard/init.sh           writes hub/_state/hub_id.txt (UUIDv4)
    federation.bootstrap_hub_id()  reads it on first Hub start
        -> INSERT INTO spine_federation.hub if not already present
        -> returns the canonical UUID for the local Hub

All operations take an asyncpg pool (or compatible DbHandle.fetch_rows
shim). Tests substitute an in-memory mock — see
``federation/tests/test_hub_registry.py``.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal, Optional, Protocol

logger = logging.getLogger("spine.federation.hub_registry")

#: Default location of the wizard-written hub_id file. Per
#: `hub/wizard/init.sh` STATE_DIR=hub/_state. Operators may override via
#: env metadata (#9 explicitly permits non-secret path overrides).
_DEFAULT_HUB_ID_FILE = Path(
    os.environ.get(
        "SPINE_HUB_ID_FILE",
        str(Path(__file__).resolve().parents[1] / "hub" / "_state" / "hub_id.txt"),
    )
)

ConsentStatus = Literal["pending", "active", "suspended", "revoked"]
"""Lifecycle states matching V23's CHECK constraint."""

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


@dataclass(frozen=True)
class HubRecord:
    """In-memory mirror of one ``spine_federation.hub`` row.

    Frozen so callers cannot mutate registry-owned state in flight; the
    registry returns a fresh dataclass on every read.
    """

    hub_id: uuid.UUID
    name: str
    base_url: str
    public_key: str
    parent_hub_id: Optional[uuid.UUID] = None
    consent_status: ConsentStatus = "pending"
    registered_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class _PoolProto(Protocol):
    """Minimal protocol for the asyncpg pool surface we depend on.

    Tests pass an in-memory mock implementing the same shape — no need
    for an actual asyncpg dependency at test time.
    """

    def acquire(self) -> Any:  # pragma: no cover - protocol stub
        ...


class HubRegistryError(RuntimeError):
    """Base error for registry operations."""


class HubNotFound(HubRegistryError):
    """Raised when a lookup by hub_id misses."""


class HubIdFileMissing(HubRegistryError):
    """Raised when bootstrap is called before the wizard has run."""


def read_hub_id_file(path: Optional[Path] = None) -> uuid.UUID:
    """Read the wizard-written hub_id file and validate it as a UUID.

    Args:
        path: Override the default location (tests). When omitted, reads
            from ``hub/_state/hub_id.txt`` (or the ``SPINE_HUB_ID_FILE``
            env override).

    Raises:
        HubIdFileMissing: if the file is absent or empty.
        ValueError: if the file content is not a parseable UUID.
    """
    p = path or _DEFAULT_HUB_ID_FILE
    if not p.is_file():
        raise HubIdFileMissing(
            f"hub_id file not found at {p}; run hub/wizard/init.sh first"
        )
    content = p.read_text(encoding="utf-8").strip()
    if not content:
        raise HubIdFileMissing(f"hub_id file at {p} is empty")
    if not _UUID_RE.match(content):
        raise ValueError(
            f"hub_id file at {p} does not contain a valid UUID (got {content!r})"
        )
    return uuid.UUID(content)


class HubRegistry:
    """Async CRUD facade over ``spine_federation.hub``.

    All methods use the asyncpg pool's ``async with pool.acquire()``
    context manager; the protocol is small enough that tests pass a
    plain ``_MockPool`` (see tests).
    """

    def __init__(self, pool: _PoolProto) -> None:
        self._pool = pool

    # ---------------------------------------------------------------
    # Bootstrap — called once on first Hub start
    # ---------------------------------------------------------------

    async def bootstrap_local_hub(
        self,
        *,
        hub_id: uuid.UUID,
        name: str,
        base_url: str,
        public_key: str,
        parent_hub_id: Optional[uuid.UUID] = None,
    ) -> HubRecord:
        """INSERT-or-FETCH the local Hub row.

        Idempotent: re-running on a Hub that's already registered returns
        the existing record without modification. The wizard guarantees a
        stable hub_id, so this is the safe lifecycle entry point.
        """
        existing = await self.get_by_hub_id(hub_id)
        if existing is not None:
            logger.info(
                "hub_bootstrap_existing",
                extra={"hub_id": str(hub_id)},
            )
            return existing
        rec = HubRecord(
            hub_id=hub_id,
            name=name,
            base_url=base_url,
            public_key=public_key,
            parent_hub_id=parent_hub_id,
            consent_status="active",
        )
        await self._insert(rec)
        logger.info(
            "hub_bootstrap_inserted",
            extra={
                "hub_id": str(hub_id),
                "parent_hub_id": str(parent_hub_id) if parent_hub_id else None,
            },
        )
        return rec

    # ---------------------------------------------------------------
    # CRUD
    # ---------------------------------------------------------------

    async def register_child(
        self,
        *,
        child_hub_id: uuid.UUID,
        name: str,
        base_url: str,
        public_key: str,
        parent_hub_id: uuid.UUID,
        initial_status: ConsentStatus = "pending",
    ) -> HubRecord:
        """INSERT a child Hub row pointing at ``parent_hub_id``.

        Returns the inserted record. Fails loud (asyncpg.UniqueViolation
        bubbles up) on duplicate ``hub_id`` so the caller can decide
        whether to update consent or reject.
        """
        rec = HubRecord(
            hub_id=child_hub_id,
            name=name,
            base_url=base_url,
            public_key=public_key,
            parent_hub_id=parent_hub_id,
            consent_status=initial_status,
        )
        await self._insert(rec)
        logger.info(
            "child_hub_registered",
            extra={
                "child_hub_id": str(child_hub_id),
                "parent_hub_id": str(parent_hub_id),
                "consent_status": initial_status,
            },
        )
        return rec

    async def get_by_hub_id(self, hub_id: uuid.UUID) -> Optional[HubRecord]:
        """SELECT one row by ``hub_id``. Returns None on miss."""
        sql = (
            "SELECT hub_id, parent_hub_id, name, base_url, public_key, "
            "       consent_status, registered_at "
            "FROM spine_federation.hub WHERE hub_id = $1"
        )
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, hub_id)
        if row is None:
            return None
        return _record_from_row(row)

    async def list_children(self, parent_hub_id: uuid.UUID) -> list[HubRecord]:
        """List every Hub whose ``parent_hub_id`` matches."""
        sql = (
            "SELECT hub_id, parent_hub_id, name, base_url, public_key, "
            "       consent_status, registered_at "
            "FROM spine_federation.hub WHERE parent_hub_id = $1 "
            "ORDER BY registered_at ASC"
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, parent_hub_id)
        return [_record_from_row(r) for r in rows]

    async def set_consent_status(
        self,
        hub_id: uuid.UUID,
        status: ConsentStatus,
    ) -> None:
        """UPDATE consent_status; raises HubNotFound on miss."""
        if status not in ("pending", "active", "suspended", "revoked"):
            raise ValueError(f"invalid consent_status {status!r}")
        sql = (
            "UPDATE spine_federation.hub SET consent_status = $1 "
            "WHERE hub_id = $2 RETURNING hub_id"
        )
        async with self._pool.acquire() as conn:
            res = await conn.fetchval(sql, status, hub_id)
        if res is None:
            raise HubNotFound(f"hub_id {hub_id} not found")
        logger.info(
            "consent_status_updated",
            extra={"hub_id": str(hub_id), "new_status": status},
        )

    # ---------------------------------------------------------------
    # Internal
    # ---------------------------------------------------------------

    async def _insert(self, rec: HubRecord) -> None:
        sql = (
            "INSERT INTO spine_federation.hub "
            "  (hub_id, parent_hub_id, name, base_url, public_key, consent_status) "
            "VALUES ($1, $2, $3, $4, $5, $6)"
        )
        async with self._pool.acquire() as conn:
            await conn.execute(
                sql,
                rec.hub_id,
                rec.parent_hub_id,
                rec.name,
                rec.base_url,
                rec.public_key,
                rec.consent_status,
            )


def _record_from_row(row: Any) -> HubRecord:
    """Coerce an asyncpg-style row mapping into a ``HubRecord``."""
    # asyncpg returns Record objects (mapping-like); tests pass plain dicts.
    def _g(key: str) -> Any:
        try:
            return row[key]
        except (KeyError, TypeError):
            return getattr(row, key)

    return HubRecord(
        hub_id=_g("hub_id"),
        parent_hub_id=_g("parent_hub_id"),
        name=_g("name"),
        base_url=_g("base_url"),
        public_key=_g("public_key"),
        consent_status=_g("consent_status"),
        registered_at=_g("registered_at"),
    )


async def bootstrap_hub_id(
    registry: HubRegistry,
    *,
    name: str,
    base_url: str,
    public_key: str,
    parent_hub_id: Optional[uuid.UUID] = None,
    hub_id_file: Optional[Path] = None,
) -> HubRecord:
    """End-to-end: read hub_id file → INSERT-or-FETCH into registry.

    This is the function called from ``hub/`` container lifespan on
    first start. The wizard's hub_id file is the source of truth; this
    function bridges it into the durable registry.
    """
    hub_id = read_hub_id_file(hub_id_file)
    return await registry.bootstrap_local_hub(
        hub_id=hub_id,
        name=name,
        base_url=base_url,
        public_key=public_key,
        parent_hub_id=parent_hub_id,
    )


__all__: list[str] = [
    "ConsentStatus",
    "HubRecord",
    "HubRegistry",
    "HubRegistryError",
    "HubNotFound",
    "HubIdFileMissing",
    "bootstrap_hub_id",
    "read_hub_id_file",
]
