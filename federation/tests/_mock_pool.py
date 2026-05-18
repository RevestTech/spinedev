"""
federation.tests._mock_pool
===========================

In-memory asyncpg-pool stand-in for unit tests.

Implements just enough of the asyncpg surface that the federation code
actually uses: `async with pool.acquire() as conn` returning an object
with `fetch`, `fetchrow`, `fetchval`, and `execute`.

Storage is a small per-table dict: rows are plain dicts keyed by SQL
column name. No real SQL parsing — the mock matches on canonical
operation tokens that the federation code happens to use.

If the federation code adds new SQL, this mock needs a matching
handler — the design is deliberate: the test bed mirrors the code's
durable surface so accidental new query shapes surface as test
failures, not silent ignores.
"""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional
from uuid import UUID, uuid4


class _MockConn:
    """Just enough asyncpg connection surface for federation tests."""

    def __init__(self, store: "_MockStore") -> None:
        self._store = store

    async def execute(self, sql: str, *args: Any) -> str:
        return self._store.execute(sql, args)

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        return self._store.fetch(sql, args)

    async def fetchrow(self, sql: str, *args: Any) -> Optional[dict[str, Any]]:
        rows = self._store.fetch(sql, args)
        return rows[0] if rows else None

    async def fetchval(self, sql: str, *args: Any) -> Any:
        rows = self._store.fetch(sql, args)
        if not rows:
            return None
        row = rows[0]
        if isinstance(row, dict) and row:
            return next(iter(row.values()))
        return row


class _MockPool:
    """`async with pool.acquire() as conn:` yields a `_MockConn`."""

    def __init__(self) -> None:
        self.store = _MockStore()

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_MockConn]:
        yield _MockConn(self.store)


class _MockStore:
    """Operation dispatcher keyed on SQL fragments the code emits."""

    def __init__(self) -> None:
        self.hubs: dict[UUID, dict[str, Any]] = {}
        self.consents: list[dict[str, Any]] = []
        self.updates: dict[UUID, dict[str, Any]] = {}

    # -- dispatch ----------------------------------------------------

    def execute(self, sql: str, args: tuple[Any, ...]) -> str:
        if "INSERT INTO spine_federation.hub " in sql:
            self._insert_hub(args)
            return "INSERT 0 1"
        if "INSERT INTO spine_federation.consent_record" in sql:
            self._insert_consent(args)
            return "INSERT 0 1"
        if "DELETE FROM spine_federation.consent_record" in sql:
            return self._delete_consent(args)
        if "UPDATE spine_federation.hub SET consent_status" in sql:
            return self._update_consent_status(args)
        if (
            "UPDATE spine_federation.update_distribution" in sql
            and "approved_at" in sql
        ):
            return self._update_distribution_full(args)
        if (
            "UPDATE spine_federation.update_distribution" in sql
            and "approved_at" not in sql
        ):
            return self._update_distribution_status(args)
        if "INSERT INTO spine_federation.update_distribution" in sql:
            self._insert_update(args)
            return "INSERT 0 1"
        raise NotImplementedError(f"_MockStore.execute: unhandled SQL: {sql[:80]}")

    def fetch(self, sql: str, args: tuple[Any, ...]) -> list[dict[str, Any]]:
        if "FROM spine_federation.hub WHERE hub_id =" in sql:
            return self._select_hub_by_id(args)
        if "FROM spine_federation.hub WHERE parent_hub_id =" in sql:
            return self._select_hubs_by_parent(args)
        if "FROM spine_federation.consent_record" in sql:
            return self._select_consent(sql, args)
        if (
            "FROM spine_federation.update_distribution" in sql
            and "WHERE id =" in sql
        ):
            return self._select_update_by_id(args)
        if (
            "FROM spine_federation.update_distribution" in sql
            and "target_hub_id" in sql
        ):
            return self._select_updates_for_target(args)
        if "UPDATE spine_federation.hub SET consent_status" in sql:
            # called via fetchval-RETURNING
            return self._update_consent_status_returning(args)
        raise NotImplementedError(f"_MockStore.fetch: unhandled SQL: {sql[:80]}")

    # -- hub ops -----------------------------------------------------

    def _insert_hub(self, args: tuple[Any, ...]) -> None:
        hub_id, parent_hub_id, name, base_url, public_key, consent_status = args
        if hub_id in self.hubs:
            raise ValueError(f"duplicate hub_id {hub_id}")
        from datetime import datetime, timezone

        self.hubs[hub_id] = {
            "hub_id": hub_id,
            "parent_hub_id": parent_hub_id,
            "name": name,
            "base_url": base_url,
            "public_key": public_key,
            "consent_status": consent_status,
            "registered_at": datetime.now(timezone.utc),
        }

    def _select_hub_by_id(self, args: tuple[Any, ...]) -> list[dict[str, Any]]:
        (hub_id,) = args
        row = self.hubs.get(hub_id)
        return [dict(row)] if row else []

    def _select_hubs_by_parent(self, args: tuple[Any, ...]) -> list[dict[str, Any]]:
        (parent_hub_id,) = args
        return [
            dict(row)
            for row in self.hubs.values()
            if row.get("parent_hub_id") == parent_hub_id
        ]

    def _update_consent_status(self, args: tuple[Any, ...]) -> str:
        status, hub_id = args
        row = self.hubs.get(hub_id)
        if row is None:
            return "UPDATE 0"
        row["consent_status"] = status
        return "UPDATE 1"

    def _update_consent_status_returning(
        self, args: tuple[Any, ...]
    ) -> list[dict[str, Any]]:
        status, hub_id = args
        row = self.hubs.get(hub_id)
        if row is None:
            return []
        row["consent_status"] = status
        return [{"hub_id": hub_id}]

    # -- consent ops -------------------------------------------------

    def _insert_consent(self, args: tuple[Any, ...]) -> None:
        child_hub_id, parent_hub_id, consent_class, granted_by, scope = args
        self.consents.append(
            {
                "child_hub_id": child_hub_id,
                "parent_hub_id": parent_hub_id,
                "consent_class": consent_class,
                "granted_by": granted_by,
                "scope": scope,
            }
        )

    def _delete_consent(self, args: tuple[Any, ...]) -> str:
        child_hub_id, parent_hub_id, consent_class = args
        before = len(self.consents)
        self.consents = [
            c
            for c in self.consents
            if not (
                c["child_hub_id"] == child_hub_id
                and c["parent_hub_id"] == parent_hub_id
                and c["consent_class"] == consent_class
            )
        ]
        return f"DELETE {before - len(self.consents)}"

    def _select_consent(
        self, sql: str, args: tuple[Any, ...]
    ) -> list[dict[str, Any]]:
        # is_allowed query: WHERE consent_class = $1 AND (child=$2 OR parent=$2)
        consent_class, peer = args
        matches = [
            c
            for c in self.consents
            if c["consent_class"] == consent_class
            and (c["child_hub_id"] == peer or c["parent_hub_id"] == peer)
        ]
        # SELECT 1 is the only fetch on this table; just return marker rows.
        return [{"?column?": 1} for _ in matches[:1]]

    # -- update_distribution ops -------------------------------------

    def _insert_update(self, args: tuple[Any, ...]) -> None:
        from datetime import datetime, timezone

        (
            id_,
            source_hub_id,
            target_hub_id,
            bundle_version,
            signature,
        ) = args
        self.updates[id_] = {
            "id": id_,
            "source_hub_id": source_hub_id,
            "target_hub_id": target_hub_id,
            "bundle_version": bundle_version,
            "signature": signature,
            "rollout_status": "pending",
            "approved_at": None,
            "approved_by": None,
            "created_at": datetime.now(timezone.utc),
        }

    def _select_update_by_id(
        self, args: tuple[Any, ...]
    ) -> list[dict[str, Any]]:
        (uid,) = args
        row = self.updates.get(uid)
        return [dict(row)] if row else []

    def _select_updates_for_target(
        self, args: tuple[Any, ...]
    ) -> list[dict[str, Any]]:
        (target,) = args
        return sorted(
            [
                dict(r)
                for r in self.updates.values()
                if r["target_hub_id"] == target and r["rollout_status"] == "pending"
            ],
            key=lambda r: r["created_at"],
        )

    def _update_distribution_full(self, args: tuple[Any, ...]) -> str:
        status, approved_at, approved_by, uid = args
        row = self.updates.get(uid)
        if row is None:
            return "UPDATE 0"
        row["rollout_status"] = status
        row["approved_at"] = approved_at
        row["approved_by"] = approved_by
        return "UPDATE 1"

    def _update_distribution_status(self, args: tuple[Any, ...]) -> str:
        status, uid = args
        row = self.updates.get(uid)
        if row is None:
            return "UPDATE 0"
        row["rollout_status"] = status
        return "UPDATE 1"


def make_pool() -> _MockPool:
    """Factory for tests."""
    return _MockPool()


def new_uuid() -> UUID:
    """UUID factory for tests."""
    return uuid4()


__all__ = ["_MockPool", "_MockConn", "_MockStore", "make_pool", "new_uuid"]
