"""Write agent-facing handoff files into a configured local checkout after an audit completes."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select

from tron.api.config import settings
from tron.domain.models import AuditRun, Finding, Project
from tron.services.scan_handoff_export import write_audit_handoff_bundle

logger = logging.getLogger(__name__)


def normalize_finding_dict(f: dict[str, Any]) -> dict[str, Any]:
    """Map persisted / agent JSON shapes to the handoff markdown builder."""
    line = f.get("line_start")
    if line is None:
        line = f.get("line_number")
    title = f.get("title")
    if not title:
        vt = f.get("vulnerability_type", "finding")
        fp = f.get("file_path", "?")
        title = f"{vt}: {fp}:{line or '?'}"
    return {
        "severity": str(f.get("severity", "medium")),
        "file_path": str(f.get("file_path", "")),
        "line_start": line,
        "title": str(title),
        "category": f.get("category") or f.get("vulnerability_type"),
    }


def audit_run_to_dict(audit: AuditRun) -> dict[str, Any]:
    return {
        "status": audit.status,
        "progress": audit.progress,
        "findings_total": audit.findings_total,
        "findings_critical": audit.findings_critical,
        "findings_high": audit.findings_high,
        "findings_medium": audit.findings_medium,
        "findings_low": audit.findings_low,
        "started_at": audit.started_at.isoformat() if audit.started_at else "",
        "completed_at": audit.completed_at.isoformat() if audit.completed_at else None,
    }


async def _load_findings_from_db(session: Any, audit_run_id: UUID) -> list[dict[str, Any]]:
    res = await session.execute(
        select(Finding).where(Finding.audit_run_id == audit_run_id)
    )
    rows = res.scalars().all()
    out: list[dict[str, Any]] = []
    for x in rows:
        out.append(
            {
                "severity": x.severity,
                "file_path": x.file_path,
                "line_start": x.line_start,
                "title": x.title,
                "category": x.category,
            }
        )
    return out


async def maybe_write_agent_handoff_after_audit(
    *,
    audit_run_id: UUID,
    project_id: UUID,
    preloaded_findings: list[dict[str, Any]] | None = None,
) -> None:
    """If ``TRON_AGENT_HANDOFF`` and ``project.agent_handoff_path`` are set, write handoff files.

    ``preloaded_findings`` should be raw agent/DB-shaped dicts (optional); otherwise findings
    are loaded from the database (must already be committed).
    """
    if not settings.tron_agent_handoff:
        return

    from tron.infra.db.session import _session_factory

    async with _session_factory() as session:
        await _maybe_write_agent_handoff_inner(
            session,
            audit_run_id=audit_run_id,
            project_id=project_id,
            preloaded_findings=preloaded_findings,
        )


async def _maybe_write_agent_handoff_inner(
    session: Any,
    *,
    audit_run_id: UUID,
    project_id: UUID,
    preloaded_findings: list[dict[str, Any]] | None,
) -> None:
    project = await session.get(Project, project_id)
    if not project:
        return
    raw_path = (project.agent_handoff_path or "").strip()
    if not raw_path:
        return

    dest = Path(raw_path).expanduser()
    if not dest.is_absolute():
        logger.warning(
            "agent_handoff_path must be absolute (got %r); skipping handoff for project %s",
            raw_path,
            project_id,
        )
        return
    if not dest.is_dir():
        logger.warning(
            "agent_handoff_path is not a directory: %s; skipping handoff",
            dest,
        )
        return
    if not os.access(dest, os.W_OK):
        logger.warning("agent_handoff_path not writable: %s; skipping handoff", dest)
        return

    audit = await session.get(AuditRun, audit_run_id)
    if not audit:
        logger.warning("Audit %s not found for handoff", audit_run_id)
        return

    if preloaded_findings is not None:
        findings = [normalize_finding_dict(f) for f in preloaded_findings]
    else:
        findings = await _load_findings_from_db(session, audit_run_id)

    audit_dict = audit_run_to_dict(audit)
    try:
        paths = write_audit_handoff_bundle(
            dest,
            app_name=project.name,
            audit_id=str(audit_run_id),
            tron_ui_base=settings.tron_ui_base,
            audit=audit_dict,
            findings=findings,
            append_tron_md_activity=settings.tron_handoff_append_tron_md,
        )
        logger.info(
            "Agent handoff written for audit %s → %s (%d files)",
            audit_run_id,
            dest,
            len(paths),
        )
    except FileNotFoundError as exc:
        logger.error("Agent handoff failed (templates?): %s", exc)
    except OSError as exc:
        logger.error("Agent handoff I/O error: %s", exc)
