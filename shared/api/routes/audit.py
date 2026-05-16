"""``/api/v2/audit`` — chronological audit trail surface (STORY-9.9.2).

Direct reads against ``spine_audit.audit_event`` (V15). Supports filter
by ``project_id`` or ``correlation_id`` and a CSV/JSON export endpoint
backing the compliance use-case in PRD §9.9 (REQ-INIT-9 FR-8).
"""

from __future__ import annotations

import csv
import io
import json as _json
from datetime import datetime
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse

from shared.api.dependencies import DbHandle, get_db_pool
from shared.audit.exporter import (
    ExportDestination,
    ExportFilters,
    ExportRequest,
    export_audit as _bulk_export,
)

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


# ──────────────────────────────────────────────────────────────────
# Bulk export — STORY-3.1.3. Streams via shared.audit.exporter,
# applies optional PII redaction (STORY-3.1.4), supports CSV / JSON /
# JSONL / Parquet to a local tmp file then streams the payload back to
# the client so we never hold the full set in memory.
# ──────────────────────────────────────────────────────────────────

BulkFormat = Literal["csv", "json", "jsonl", "parquet"]
_MEDIA = {"csv": "text/csv", "json": "application/json",
          "jsonl": "application/x-ndjson", "parquet": "application/octet-stream"}


@router.get("/export/v2")
async def export_audit_v2(
    fmt: BulkFormat = Query(default="jsonl", alias="format"),
    project_id: Optional[str] = Query(default=None),
    role: Optional[str] = Query(default=None),
    subsystem: Optional[str] = Query(default=None),
    action: Optional[str] = Query(default=None),
    correlation_id: Optional[str] = Query(default=None),
    from_ts: Optional[datetime] = Query(default=None, alias="from"),
    to_ts: Optional[datetime] = Query(default=None, alias="to"),
    redact: bool = Query(default=True),
    include_payloads: bool = Query(default=False),
    chunk_size: int = Query(default=10000, ge=100, le=100000),
) -> StreamingResponse:
    """Stream a filtered bulk export through ``shared.audit.exporter``.

    Backed by the same code path as the ``spine audit export`` CLI so
    behaviour matches across surfaces. Writes through a tmp file and
    re-streams to the client to keep the request body bounded.
    """
    import os
    import tempfile

    req = ExportRequest(
        format=fmt,
        filters=ExportFilters(project_id=project_id, role=role, subsystem=subsystem,
                              action=action, correlation_id=correlation_id,
                              from_ts=from_ts, to_ts=to_ts),
        destination=ExportDestination(kind="file",
                                      path=tempfile.NamedTemporaryFile(
                                          suffix=f".{fmt}", delete=False).name),
        include_payloads=include_payloads,
        redact_pii=redact,
        chunk_size=chunk_size,
    )
    try:
        result = _bulk_export(req)
    except RuntimeError as exc:
        raise _err(502, "export_error", str(exc)) from exc
    fname = f"audit-export.{fmt}"
    headers = {"Content-Disposition": f'attachment; filename="{fname}"',
               "X-Spine-Audit-Rows": str(result.rows_exported),
               "X-Spine-Audit-Redactions": str(result.pii_redactions)}

    def _iter() -> Any:
        try:
            with open(req.destination.path or "", "rb") as fh:
                while chunk := fh.read(64 * 1024):
                    yield chunk
        finally:
            try:
                os.unlink(req.destination.path or "")
            except OSError:
                pass

    return StreamingResponse(_iter(), media_type=_MEDIA[fmt], headers=headers)
