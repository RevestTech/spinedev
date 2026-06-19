"""Instinct promotion loop — periodic ``check_promotion`` sweep (SPINE-006).

For each active project, collects instinct fingerprints from that project's
JSONL store and runs :func:`learning.instinct.check_promotion` once per
distinct fingerprint per tick. Eligible promotions are logged for downstream
lesson promotion (``promote_to_lesson_payload`` + ``contribute_lesson``).

Enabled when ``SPINE_INSTINCT_PROMOTION=1``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("spine.runtime.instinct_promotion_loop")

_POLL_SECS = float(os.environ.get("SPINE_INSTINCT_PROMOTION_POLL_SECS", "300"))


async def fetch_active_project_ids() -> list[str]:
    """Load active project UUIDs from Postgres; empty when DB unavailable."""
    from shared.api.dependencies import DbPoolNotInitialized, get_db_pool_raw  # noqa: PLC0415

    try:
        pool = get_db_pool_raw()
    except DbPoolNotInitialized:
        return []

    if pool is None:
        return []

    sql = """
    SELECT project_uuid::text AS project_uuid
    FROM spine_lifecycle.project
    WHERE status = 'active'
    ORDER BY updated_at DESC
    LIMIT 100
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql)
    return [str(r["project_uuid"]) for r in rows]


def collect_project_fingerprints(
    project_id: str,
    *,
    root: Path | None = None,
) -> set[str]:
    """Return distinct instinct fingerprints recorded for ``project_id``."""
    from learning.instinct import InstinctRecord, default_instinct_root  # noqa: PLC0415

    root = root or default_instinct_root()
    project_dir = root / project_id
    if not project_dir.is_dir():
        return set()

    fingerprints: set[str] = set()
    for run_file in sorted(project_dir.glob("*.jsonl")):
        with run_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = InstinctRecord.model_validate_json(line)
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "instinct_promotion_skip_malformed",
                        extra={"project_id": project_id, "path": str(run_file)},
                    )
                    continue
                fingerprints.add(record.fingerprint)
    return fingerprints


def sweep_project_promotions(
    project_ids: list[str],
    *,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """Run ``check_promotion`` for fingerprints under each active project.

    Returns one dict per eligible fingerprint with the triggering project id
    and the :class:`PromotionDecision`.
    """
    from learning.instinct import PromotionDecision, check_promotion, default_instinct_root  # noqa: PLC0415

    root = root or default_instinct_root()
    seen: set[str] = set()
    eligible: list[dict[str, Any]] = []

    for project_id in project_ids:
        for fingerprint in collect_project_fingerprints(project_id, root=root):
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            decision: PromotionDecision = check_promotion(fingerprint, root=root)
            if decision.eligible_for_promotion:
                eligible.append({
                    "project_id": project_id,
                    "fingerprint": fingerprint,
                    "decision": decision,
                })
                logger.info(
                    "instinct_promotion_eligible",
                    extra={
                        "project_id": project_id,
                        "fingerprint": fingerprint[:12],
                        "observations": decision.observations,
                        "projects_seen": len(decision.projects_seen),
                    },
                )
    return eligible


async def instinct_promotion_tick() -> int:
    """One poll cycle. Returns count of eligible promotion decisions."""
    project_ids = await fetch_active_project_ids()
    if not project_ids:
        return 0
    return len(sweep_project_promotions(project_ids))


async def run_instinct_promotion_loop(stop: asyncio.Event) -> None:
    """Background loop until ``stop`` is set."""
    logger.info("instinct_promotion_loop_started", extra={"poll_secs": _POLL_SECS})
    while not stop.is_set():
        try:
            count = await instinct_promotion_tick()
            if count:
                logger.info("instinct_promotion_tick", extra={"eligible": count})
        except Exception as exc:  # noqa: BLE001
            logger.warning("instinct_promotion_tick_failed", extra={"error": str(exc)})
        try:
            await asyncio.wait_for(stop.wait(), timeout=_POLL_SECS)
        except asyncio.TimeoutError:
            continue
    logger.info("instinct_promotion_loop_stopped")


def promotion_loop_enabled() -> bool:
    raw = os.environ.get("SPINE_INSTINCT_PROMOTION", "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


__all__ = [
    "collect_project_fingerprints",
    "fetch_active_project_ids",
    "instinct_promotion_tick",
    "promotion_loop_enabled",
    "run_instinct_promotion_loop",
    "sweep_project_promotions",
]
