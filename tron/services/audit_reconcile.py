"""Mark long-lived ``queued`` audit runs as failed (worker / Temporal drift cleanup)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tron.domain.models import AuditRun

logger = logging.getLogger(__name__)

_STALE_MESSAGE = (
    "Reconciled: remained queued beyond threshold (no DB progress — check "
    "`tron-worker`, Temporal, and workflow history)."
)


@dataclass(frozen=True)
class ReconcileStaleQueuedResult:
    matched: int
    updated: int
    dry_run: bool
    audit_run_ids: List[str]


async def reconcile_stale_queued_audits(
    session: AsyncSession,
    *,
    older_than_minutes: int,
    dry_run: bool = False,
) -> ReconcileStaleQueuedResult:
    """
    Select ``audit_runs`` with ``status == 'queued'`` and ``created_at`` older than
    ``older_than_minutes``, then set ``failed`` + ``completed_at`` (unless ``dry_run``).
    """
    if older_than_minutes < 1:
        raise ValueError("older_than_minutes must be >= 1")

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)

    res = await session.execute(
        select(AuditRun.id).where(
            AuditRun.status == "queued",
            AuditRun.created_at < cutoff,
        )
    )
    ids = list(res.scalars().all())
    id_strs = [str(i) for i in ids]

    if dry_run or not ids:
        if dry_run and ids:
            logger.info(
                "reconcile stale queued (dry-run): would update %d audit(s) older than %s min",
                len(ids),
                older_than_minutes,
            )
        return ReconcileStaleQueuedResult(
            matched=len(ids),
            updated=0,
            dry_run=dry_run,
            audit_run_ids=id_strs,
        )

    await session.execute(
        update(AuditRun)
        .where(AuditRun.id.in_(ids))
        .values(
            status="failed",
            error_message=_STALE_MESSAGE[:1000],
            completed_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()

    logger.warning(
        "reconcile stale queued: marked %d audit run(s) failed (older_than_minutes=%s)",
        len(ids),
        older_than_minutes,
    )

    return ReconcileStaleQueuedResult(
        matched=len(ids),
        updated=len(ids),
        dry_run=False,
        audit_run_ids=id_strs,
    )
