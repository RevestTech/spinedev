"""``/api/v2/audit`` — chronological audit trail surface (STORY-9.9.2).

Direct reads against ``spine_audit.audit_event`` (V15). Supports filter
by ``project_id`` or ``correlation_id`` and a CSV/JSON export endpoint
backing the compliance use-case in PRD §9.9 (REQ-INIT-9 FR-8).
"""

from __future__ import annotations

import csv
import io
import json as _json
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from shared.api.dependencies import DbHandle, get_db_pool

router = APIRouter(prefix="/api/v2/audit", tags=["audit"])

ExportFormat = Literal["csv", "json"]

_COLS = (
    "event_id", "event_uuid", "ts", "project_id", "phase", "role", "subsystem",
    "action", "subject_type", "subject_id", "actor", "rationale", "cost_usd",
    "correlation_id", "pipeline_version",
)


def _err(code: int, ec: str, msg: str) -> HTTPException:
    """Standard structured HTTPException."""
    return HTTPException(status_code=code, detail={"error_code": ec, "message": msg})


def _esc(s: str) -> str:
    """Defence-in-depth single-quote escape."""
    return s.replace("'", "''")


def _query(*, project_id: str | None, correlation_id: str | None, limit: int) -> str:
    """Build the ``SELECT`` for audit endpoints — JSON per row, ts asc."""
    where = ["1=1"]
    if project_id:
        where.append(f"project_id::text = '{_esc(project_id)}'")
    if correlation_id:
        where.append(f"correlation_id::text = '{_esc(correlation_id)}'")
    cols = ", ".join(f"'{c}', {c}" for c in _COLS)
    return (
        f"SELECT json_build_object({cols})::text FROM spine_audit.audit_event "
        f"WHERE {' AND '.join(where)} ORDER BY ts ASC, event_id ASC LIMIT {limit};"
    )


@router.get("")
async def list_audit(
    db: Annotated[DbHandle, Depends(get_db_pool)],
    project_id: Optional[str] = Query(default=None),
    correlation_id: Optional[str] = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
) -> dict[str, Any]:
    """Chronological audit trail filtered by project or correlation."""
    if not project_id and not correlation_id:
        raise _err(400, "invalid_input", "project_id or correlation_id required")
    try:
        rows = await db.fetch(_query(project_id=project_id, correlation_id=correlation_id, limit=limit))
    except RuntimeError as exc:
        raise _err(502, "db_error", str(exc)) from exc
    return {
        "ok": True, "items": [r["_row"] for r in rows],
        "project_id": project_id, "correlation_id": correlation_id, "limit": limit,
    }


@router.get("/export")
async def export_audit(
    db: Annotated[DbHandle, Depends(get_db_pool)],
    project_id: str = Query(..., min_length=1),
    fmt: ExportFormat = Query(default="json", alias="format"),
    limit: int = Query(default=5000, ge=1, le=50000),
) -> Response:
    """Export per-project audit trail as JSON or CSV (attachment download)."""
    try:
        rows = await db.fetch(_query(project_id=project_id, correlation_id=None, limit=limit))
    except RuntimeError as exc:
        raise _err(502, "db_error", str(exc)) from exc
    raw = [r["_row"] for r in rows]
    fname = f"audit-{project_id}.{fmt}"
    headers = {"Content-Disposition": f'attachment; filename="{fname}"'}
    if fmt == "json":
        return Response(content="[" + ",".join(raw) + "]",
                        media_type="application/json", headers=headers)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(_COLS), extrasaction="ignore")
    writer.writeheader()
    for line in raw:
        try:
            writer.writerow(_json.loads(line))
        except _json.JSONDecodeError:
            continue
    return Response(content=buf.getvalue(), media_type="text/csv", headers=headers)
