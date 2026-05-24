"""Master role portfolio briefings (#5 / #8 P2).

Aggregates active projects into director-level daily briefings and pushes
them to the Decision Queue as ``decision_class=briefing`` cards. Runs as a
background loop alongside ``phase_watcher`` when ``SPINE_MASTER_BRIEFING=1``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("spine.runtime.master_briefing")

_POLL_SECS = float(os.environ.get("SPINE_MASTER_BRIEFING_POLL_SECS", "3600"))
_BRIEFING_KIND = "master_daily_briefing"

_MASTER_DIRECTORS: tuple[tuple[str, str], ...] = (
    ("director_product", "Portfolio product status"),
    ("director_engineering", "Build + verify health"),
    ("director_devops", "Deploy + release posture"),
    ("director_security", "Security + compliance posture"),
)


@dataclass
class ProjectRow:
    project_uuid: str
    name: str
    current_phase: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PortfolioSnapshot:
    projects: list[ProjectRow] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def active_count(self) -> int:
        return len(self.projects)

    def by_phase(self) -> dict[str, list[ProjectRow]]:
        out: dict[str, list[ProjectRow]] = {}
        for p in self.projects:
            out.setdefault(p.current_phase, []).append(p)
        return out

    def blocked(self) -> list[ProjectRow]:
        blocked: list[ProjectRow] = []
        for p in self.projects:
            md = p.metadata or {}
            if md.get("code_review_blocked"):
                blocked.append(p)
            elif md.get("devops_install_ok") is False:
                blocked.append(p)
        return blocked


async def fetch_portfolio_snapshot() -> PortfolioSnapshot:
    """Load active projects from Postgres; empty snapshot when DB unavailable."""
    from shared.api.dependencies import DbPoolNotInitialized, get_db_pool_raw  # noqa: PLC0415

    try:
        pool = get_db_pool_raw()
    except DbPoolNotInitialized:
        return PortfolioSnapshot()

    sql = """
    SELECT project_uuid::text AS project_uuid,
           name,
           current_phase,
           COALESCE(metadata, '{}'::jsonb) AS metadata
    FROM spine_lifecycle.project
    WHERE status = 'active'
    ORDER BY updated_at DESC
    LIMIT 100
    """
    rows: list[ProjectRow] = []
    async with pool.acquire() as conn:
        result = await conn.fetch(sql)
    for r in result:
        md = r["metadata"]
        if isinstance(md, str):
            import json

            md = json.loads(md or "{}")
        rows.append(ProjectRow(
            project_uuid=str(r["project_uuid"]),
            name=str(r["name"]),
            current_phase=str(r["current_phase"]),
            metadata=dict(md or {}),
        ))
    return PortfolioSnapshot(projects=rows)


def compose_director_briefing(director: str, title: str, snap: PortfolioSnapshot) -> str:
    """Render markdown briefing body for one master director."""
    lines = [
        f"# {title}",
        "",
        f"_Generated {snap.generated_at.isoformat(timespec='minutes')}_",
        "",
        f"**Active projects:** {snap.active_count}",
        "",
    ]
    blocked = snap.blocked()
    if blocked:
        lines.append("## Blockers")
        for p in blocked:
            reason = "code review blocked" if (p.metadata or {}).get("code_review_blocked") else "devops install failed"
            lines.append(f"- **{p.name}** ({p.current_phase}) — {reason}")
        lines.append("")

    lines.append("## By phase")
    for phase, projects in sorted(snap.by_phase().items()):
        lines.append(f"### {phase} ({len(projects)})")
        for p in projects[:8]:
            md = p.metadata or {}
            artifact = next(
                (k for k in ("prd_md", "roadmap_md", "trd_md", "code_intro_md", "qa_md", "release_gate_md")
                 if md.get(k)),
                "intake",
            )
            lines.append(f"- **{p.name}** — latest artifact: `{artifact}`")
        if len(projects) > 8:
            lines.append(f"- _…and {len(projects) - 8} more_")
        lines.append("")

    if director == "director_security":
        lines.append("## Security note")
        lines.append(
            "Verify-class roles must cite KG node ids or file:line per #12. "
            "Review any blocked code-review cards before override."
        )
    elif director == "director_devops":
        lines.append("## Deploy note")
        lines.append(
            "Projects in ``released`` phase may await ``local_deploy_prompt`` ack. "
            "Cloud deploy commands remain in ``release_gate_md`` until vault creds wire up."
        )

    lines.append("")
    lines.append("_Ack to dismiss; reject to request a revised briefing._")
    return "\n".join(lines)


def _already_pending(director: str) -> bool:
    """Skip if a pending master briefing for this director already exists."""
    try:
        from shared.api.routes.decisions import get_store  # noqa: PLC0415
    except Exception:
        return False

    for card in get_store().list(status_filter="pending"):
        meta = card.metadata or {}
        if meta.get("kind") != _BRIEFING_KIND:
            continue
        if meta.get("director") != director:
            continue
        return True
    return False


def push_master_briefings(snap: PortfolioSnapshot | None = None) -> int:
    """Enqueue briefing cards for each master director. Returns count pushed."""
    if snap is None:
        return 0

    from shared.api.routes.decisions import DecisionCard, enqueue_decision  # noqa: PLC0415

    pushed = 0
    for director, title in _MASTER_DIRECTORS:
        if _already_pending(director):
            continue
        body = compose_director_briefing(director, title, snap)
        enqueue_decision(DecisionCard(
            decision_id=str(uuid.uuid4()),
            decision_class="briefing",
            title=f"Daily briefing — {title}",
            body=body,
            severity="info",
            actions=["ack", "reject"],
            metadata={
                "kind": _BRIEFING_KIND,
                "director": director,
                "project_count": snap.active_count,
            },
        ))
        pushed += 1
        logger.info("master_briefing_pushed", extra={"director": director})
    return pushed


async def master_briefing_tick() -> int:
    snap = await fetch_portfolio_snapshot()
    if snap.active_count == 0:
        return 0
    return push_master_briefings(snap)


async def run_master_briefing_loop(stop: asyncio.Event) -> None:
    logger.info("master_briefing_started", extra={"poll_secs": _POLL_SECS})
    while not stop.is_set():
        try:
            count = await master_briefing_tick()
            if count:
                logger.info("master_briefing_tick", extra={"pushed": count})
        except Exception as exc:  # noqa: BLE001
            logger.warning("master_briefing_tick_failed", extra={"error": str(exc)})
        try:
            await asyncio.wait_for(stop.wait(), timeout=_POLL_SECS)
        except asyncio.TimeoutError:
            continue
    logger.info("master_briefing_stopped")


def briefing_enabled() -> bool:
    raw = os.environ.get("SPINE_MASTER_BRIEFING", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


__all__ = [
    "PortfolioSnapshot",
    "ProjectRow",
    "briefing_enabled",
    "compose_director_briefing",
    "fetch_portfolio_snapshot",
    "master_briefing_tick",
    "push_master_briefings",
    "run_master_briefing_loop",
]
