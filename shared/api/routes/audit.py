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


def _query(
    *,
    project_id: str | None,
    correlation_id: str | None,
    subsystem: str | None = None,
    role: str | None = None,
    action: str | None = None,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    after_event_id: int | None = None,
    limit: int,
) -> str:
    """Build the ``SELECT`` for audit endpoints — JSON per row, ts asc.

    Wave 3.5 FIX3: now also accepts ``subsystem`` / ``role`` / ``action``
    text filters, ``from_ts`` / ``to_ts`` window bounds, and an
    ``after_event_id`` cursor. ``event_id`` is BIGSERIAL append-only
    (V15) so it is a stable monotonic cursor; the WHERE clause uses
    ``event_id > <cursor>`` to walk strictly forward.
    """
    where = ["1=1"]
    if project_id:
        where.append(f"project_id::text = '{_esc(project_id)}'")
    if correlation_id:
        where.append(f"correlation_id::text = '{_esc(correlation_id)}'")
    if subsystem:
        where.append(f"subsystem = '{_esc(subsystem)}'")
    if role:
        where.append(f"role = '{_esc(role)}'")
    if action:
        where.append(f"action = '{_esc(action)}'")
    if from_ts is not None:
        where.append(f"ts >= '{_esc(from_ts.isoformat())}'::timestamptz")
    if to_ts is not None:
        where.append(f"ts <= '{_esc(to_ts.isoformat())}'::timestamptz")
    if after_event_id is not None:
        where.append(f"event_id > {int(after_event_id)}")
    cols = ", ".join(f"'{c}', {c}" for c in _COLS)
    return (
        f"SELECT json_build_object({cols})::text FROM spine_audit.audit_event "
        f"WHERE {' AND '.join(where)} ORDER BY event_id ASC LIMIT {limit};"
    )


@router.get("")
async def list_audit(
    db: Annotated[DbHandle, Depends(get_db_pool)],
    project_id: Optional[str] = Query(default=None),
    correlation_id: Optional[str] = Query(default=None),
    subsystem: Optional[str] = Query(default=None),
    role: Optional[str] = Query(default=None),
    action: Optional[str] = Query(default=None),
    from_ts: Optional[datetime] = Query(default=None, alias="from_ts"),
    to_ts: Optional[datetime] = Query(default=None, alias="to_ts"),
    after_event_id: Optional[int] = Query(default=None, ge=0),
    limit: int = Query(default=500, ge=1, le=5000),
) -> dict[str, Any]:
    """Chronological audit trail with multi-axis filters + cursor pagination.

    Wave 3.5 FIX3:

    * Either ``project_id`` OR ``correlation_id`` is still required so a
      caller cannot accidentally page the entire fleet (filter-or-refuse).
    * Optional ``subsystem`` / ``role`` / ``action`` / ``from_ts`` /
      ``to_ts`` may co-occur in any combination.
    * ``after_event_id`` is a BIGINT cursor (event_id is append-only
      monotonic per V15) — pass back the ``next_cursor`` returned in the
      previous response. ``next_cursor`` is ``null`` when the page is
      shorter than ``limit`` (caller has caught up).
    """
    if not project_id and not correlation_id:
        raise _err(400, "invalid_input", "project_id or correlation_id required")
    sql = _query(
        project_id=project_id,
        correlation_id=correlation_id,
        subsystem=subsystem,
        role=role,
        action=action,
        from_ts=from_ts,
        to_ts=to_ts,
        after_event_id=after_event_id,
        limit=limit,
    )
    try:
        rows = await db.fetch(sql)
    except RuntimeError as exc:
        raise _err(502, "db_error", str(exc)) from exc
    items = [r["_row"] for r in rows]
    # Compute next_cursor from the last row's event_id (parsed cheaply
    # from the JSON text we already shipped). When we returned a full
    # page we assume there *may* be more; if shorter than ``limit`` the
    # caller has caught up and we signal end-of-stream with ``None``.
    next_cursor: Optional[int] = None
    if len(items) >= limit and items:
        try:
            last = _json.loads(items[-1])
            ev = last.get("event_id")
            next_cursor = int(ev) if ev is not None else None
        except (_json.JSONDecodeError, TypeError, ValueError):
            next_cursor = None
    return {
        "ok": True, "items": items,
        "project_id": project_id, "correlation_id": correlation_id,
        "subsystem": subsystem, "role": role, "action": action,
        "from_ts": from_ts.isoformat() if from_ts else None,
        "to_ts": to_ts.isoformat() if to_ts else None,
        "after_event_id": after_event_id,
        "limit": limit,
        "next_cursor": next_cursor,
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
        rows = await db.fetch(_query(
            project_id=project_id, correlation_id=None, limit=limit,
        ))
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
