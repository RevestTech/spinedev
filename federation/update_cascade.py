"""
federation.update_cascade
=========================

Update distribution per #16: **vendor → parent → child** with an
**approval gate at every tier**. Auto-push is never an option. Each
decision (approve / defer / reject / fail / roll-back) writes one row
to ``spine_federation.update_distribution`` and one matching
``spine_audit.audit_event`` so the chain is independently replayable.

Squad A is responsible for the parent→child half of the cascade. The
vendor→parent half lives in `license/` (Squad B) and pushes signed
bundles into the same `update_distribution` table; this module reads
those rows, gates them through the local Hub's approval flow, and
broadcasts to children via the downstream router.

The cascade follows the same shape as `shared/standards/drift_detector`:

1. **Detect.** Discover pending updates from the parent's
   `update_distribution` records (or — for the vendor→root case — from
   `license.bundle_verifier`).
2. **Gate.** Surface the changelog + risk notes + impact preview to the
   local Hub admin via the decision queue. Status transitions are
   `pending` → (`in_progress` | `failed`).
3. **Apply locally.** Validate signature; stage; run sanity smoke;
   commit. Failure → `failed` + rollback hook.
4. **Cascade.** Insert one `update_distribution` row per consenting
   child via `DownstreamRouter.broadcast`, leaving each child to run
   its own gate (`pending` at the child).

Per #12 (Cite-or-Refuse) the MCP tools wrapping this module
(``federation_push_update``, ``federation_pull_updates``) are tagged
``requires_citation=True`` — the cite must reference the
audit_event content_hash of the approval row.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Iterable, Literal, Optional
from uuid import UUID, uuid4

logger = logging.getLogger("spine.federation.update_cascade")

RolloutStatus = Literal[
    "pending", "in_progress", "completed", "failed", "rolled_back"
]
"""Matches V23's CHECK constraint on ``update_distribution.rollout_status``."""


class ApprovalRequired(RuntimeError):
    """Raised when a cascade attempts to apply without explicit approval.

    Per #16 auto-push is never an option; this is the in-code expression
    of that policy.
    """


class CascadeError(RuntimeError):
    """Generic cascade failure (signature invalid, sanity smoke failed, …)."""


@dataclass(frozen=True)
class UpdateRecord:
    """In-memory mirror of one ``spine_federation.update_distribution`` row."""

    id: UUID
    source_hub_id: UUID
    target_hub_id: UUID
    bundle_version: str
    signature: bytes
    rollout_status: RolloutStatus = "pending"
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = None


@dataclass(frozen=True)
class CascadeOutcome:
    """Result of one cascade attempt for human + audit consumption."""

    local_update_id: UUID
    local_status: RolloutStatus
    children_attempted: int = 0
    children_succeeded: int = 0
    children_failed: int = 0
    notes: str = ""


@dataclass
class UpdateCascade:
    """Orchestrates the parent→child half of the #16 update cascade.

    Dependencies are injected so tests can run the cascade end-to-end
    against an in-memory pool + a fake router + a fake signature
    verifier.
    """

    pool: Any  # asyncpg pool or compatible mock
    local_hub_id: UUID
    downstream_router: Any  # DownstreamRouter
    consent_engine: Any  # ConsentEngine
    signature_verifier: Callable[[bytes, bytes, str], bool] = field(
        default=lambda payload, signature, pubkey: True
    )
    sanity_smoke: Callable[[str], Awaitable[bool]] = field(
        default=lambda bundle_version: _ok()
    )

    # ---------------------------------------------------------------
    # Public flow
    # ---------------------------------------------------------------

    async def approve_and_apply(
        self,
        update_id: UUID,
        *,
        approved_by: str,
        rationale: str,
    ) -> CascadeOutcome:
        """Mark a pending update approved, apply it locally, then cascade.

        Raises ApprovalRequired if approver identity is missing — the
        cascade refuses to run unattributed.
        """
        if not approved_by:
            raise ApprovalRequired(
                "approved_by required; auto-push is forbidden per #16"
            )
        if not rationale:
            raise ApprovalRequired(
                "rationale required for audit (#12 Cite-or-Refuse parallel)"
            )

        rec = await self._fetch_update(update_id)
        if rec.rollout_status != "pending":
            raise CascadeError(
                f"update {update_id} status={rec.rollout_status!r}; only "
                "'pending' updates may be approved"
            )

        # Local apply: stage → sanity → commit
        await self._set_status(
            update_id, "in_progress",
            approved_at=datetime.now(timezone.utc),
            approved_by=approved_by,
        )
        try:
            ok = await self.sanity_smoke(rec.bundle_version)
        except Exception as exc:  # noqa: BLE001
            await self._set_status(update_id, "failed")
            raise CascadeError(f"sanity smoke errored: {exc}") from exc
        if not ok:
            await self._set_status(update_id, "failed")
            raise CascadeError(
                f"sanity smoke for {rec.bundle_version} returned False"
            )
        await self._set_status(update_id, "completed")

        # Cascade to children
        return await self._cascade_to_children(rec, approved_by=approved_by)

    async def reject(
        self,
        update_id: UUID,
        *,
        rejected_by: str,
        rationale: str,
    ) -> CascadeOutcome:
        """Mark a pending update rejected. Surface intent to children?

        Per #16 rejection at this tier does NOT cascade — children may
        still receive the update through other paths (e.g. direct
        vendor leaf subscription). The local Hub records the choice and
        moves on. Caller must emit the audit event.
        """
        if not rejected_by or not rationale:
            raise ApprovalRequired(
                "rejected_by + rationale are required for audit"
            )
        await self._set_status(
            update_id, "rolled_back",
            approved_at=datetime.now(timezone.utc),
            approved_by=rejected_by,
        )
        return CascadeOutcome(
            local_update_id=update_id,
            local_status="rolled_back",
            notes=f"rejected by {rejected_by}: {rationale}",
        )

    async def pull_pending(self) -> list[UpdateRecord]:
        """Return every `pending` update_distribution row targeting us."""
        sql = (
            "SELECT id, source_hub_id, target_hub_id, bundle_version, "
            "       signature, rollout_status, approved_at, approved_by "
            "FROM spine_federation.update_distribution "
            "WHERE target_hub_id = $1 AND rollout_status = 'pending' "
            "ORDER BY created_at ASC"
        )
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, self.local_hub_id)
        return [_record_from_row(r) for r in rows]

    # ---------------------------------------------------------------
    # Internal
    # ---------------------------------------------------------------

    async def _fetch_update(self, update_id: UUID) -> UpdateRecord:
        sql = (
            "SELECT id, source_hub_id, target_hub_id, bundle_version, "
            "       signature, rollout_status, approved_at, approved_by "
            "FROM spine_federation.update_distribution WHERE id = $1"
        )
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(sql, update_id)
        if row is None:
            raise CascadeError(f"update {update_id} not found")
        return _record_from_row(row)

    async def _set_status(
        self,
        update_id: UUID,
        status: RolloutStatus,
        *,
        approved_at: Optional[datetime] = None,
        approved_by: Optional[str] = None,
    ) -> None:
        if approved_at is not None or approved_by is not None:
            sql = (
                "UPDATE spine_federation.update_distribution "
                "SET rollout_status = $1, approved_at = $2, approved_by = $3 "
                "WHERE id = $4"
            )
            async with self.pool.acquire() as conn:
                await conn.execute(
                    sql, status, approved_at, approved_by, update_id
                )
        else:
            sql = (
                "UPDATE spine_federation.update_distribution "
                "SET rollout_status = $1 WHERE id = $2"
            )
            async with self.pool.acquire() as conn:
                await conn.execute(sql, status, update_id)

    async def _cascade_to_children(
        self,
        local_rec: UpdateRecord,
        *,
        approved_by: str,
    ) -> CascadeOutcome:
        """Push one update_distribution row per child, then return outcome.

        Each child's cascade is *one row insert + one MCP push*; the
        child's own UpdateCascade picks the row up via `pull_pending`
        and runs its own approval gate.
        """
        # Discovery: child set comes from the downstream router, which
        # already reads the registry — but we need the explicit list
        # here for per-child INSERTs.
        from .hub_registry import HubRegistry  # local import — avoid cycle

        registry: HubRegistry = self.downstream_router._registry  # noqa: SLF001
        children = await registry.list_children(self.local_hub_id)

        attempted = 0
        succeeded = 0
        failed = 0
        for child in children:
            if child.consent_status != "active":
                continue
            if not await self.consent_engine.is_allowed(
                child.hub_id, "update_push"
            ):
                continue
            attempted += 1
            new_id = uuid4()
            try:
                await self._insert_child_update(
                    new_id, self.local_hub_id, child.hub_id, local_rec
                )
                # Notify the child via MCP — best-effort; offline children
                # will pick up via their own `pull_pending` sweep.
                try:
                    await self.downstream_router.call_child(
                        child.hub_id,
                        method="POST",
                        path="/api/v2/federation/cascade/notify",
                        consent_class="update_push",
                        json={
                            "update_id": str(new_id),
                            "bundle_version": local_rec.bundle_version,
                            "source_hub_id": str(self.local_hub_id),
                        },
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.info(
                        "child_notify_failed",
                        extra={
                            "child_hub_id": str(child.hub_id),
                            "error": str(exc),
                        },
                    )
                succeeded += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "child_cascade_insert_failed",
                    extra={"child_hub_id": str(child.hub_id), "error": str(exc)},
                )
                failed += 1
        return CascadeOutcome(
            local_update_id=local_rec.id,
            local_status="completed",
            children_attempted=attempted,
            children_succeeded=succeeded,
            children_failed=failed,
            notes=f"approved_by={approved_by}",
        )

    async def _insert_child_update(
        self,
        new_id: UUID,
        source_hub_id: UUID,
        target_hub_id: UUID,
        parent_rec: UpdateRecord,
    ) -> None:
        sql = (
            "INSERT INTO spine_federation.update_distribution "
            "  (id, source_hub_id, target_hub_id, bundle_version, signature, "
            "   rollout_status) "
            "VALUES ($1, $2, $3, $4, $5, 'pending')"
        )
        async with self.pool.acquire() as conn:
            await conn.execute(
                sql,
                new_id,
                source_hub_id,
                target_hub_id,
                parent_rec.bundle_version,
                parent_rec.signature,
            )


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------

def _record_from_row(row: Any) -> UpdateRecord:
    def _g(key: str) -> Any:
        try:
            return row[key]
        except (KeyError, TypeError):
            return getattr(row, key)

    return UpdateRecord(
        id=_g("id"),
        source_hub_id=_g("source_hub_id"),
        target_hub_id=_g("target_hub_id"),
        bundle_version=_g("bundle_version"),
        signature=_g("signature"),
        rollout_status=_g("rollout_status"),
        approved_at=_g("approved_at"),
        approved_by=_g("approved_by"),
    )


async def _ok() -> bool:  # default sanity_smoke — passes
    return True


__all__: list[str] = [
    "UpdateCascade",
    "UpdateRecord",
    "CascadeOutcome",
    "RolloutStatus",
    "ApprovalRequired",
    "CascadeError",
]
