"""``/api/v2/approvals`` — approval queue REST surface (STORY-9.9.2).

Wraps ``orchestrator/lib/gate.sh`` (list-pending / approve / reject /
request-changes) and ``spine_lifecycle.approval`` reads. Hub SPA decision
queue consumes this API (replaces the retired static ``shared/ui/approvals/`` dev UI).
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from shared.api.dependencies import (
    DbHandle,
    actor_label,
    current_user,
    get_db_pool,
)
from shared.identity.models import User

router = APIRouter(prefix="/api/v2/approvals", tags=["approvals"])

ApprovalAction = Literal["approve", "reject", "request_changes"]
ApprovalStatus = Literal["pending", "approved", "rejected", "request_changes"]

SPINE_ROOT = pathlib.Path(os.environ.get("SPINE_ROOT", pathlib.Path(__file__).resolve().parents[3]))
GATE_SH = pathlib.Path(os.environ.get("SPINE_GATE_SH", SPINE_ROOT / "orchestrator/lib/gate.sh"))


def _err(code: int, ec: str, msg: str, details: dict[str, Any] | None = None) -> HTTPException:
    """Standard structured HTTPException."""
    body: dict[str, Any] = {"error_code": ec, "message": msg}
    if details is not None:
        body["details"] = details
    return HTTPException(status_code=code, detail=body)


def _gate(*args: str) -> tuple[int, str, str]:
    """Invoke ``gate.sh`` with args; capture stdout/stderr/rc."""
    try:
        r = subprocess.run(["bash", str(GATE_SH), *args],
                           capture_output=True, text=True, timeout=30)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    except subprocess.TimeoutExpired:
        return 124, "", "gate.sh timed out"


def _parse_last_json(stdout: str) -> dict[str, Any] | None:
    """Return the last JSON object on stdout, or None if unparseable."""
    if not stdout.strip():
        return None
    try:
        return json.loads(stdout.strip().splitlines()[-1])
    except json.JSONDecodeError:
        return None


class ApprovalDecision(BaseModel):
    """Body for ``POST /api/v2/approvals``."""

    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(..., min_length=1)
    phase: Optional[str] = Field(default=None, description="Defaults to current phase.")
    action: ApprovalAction
    approver: Optional[str] = None
    notes: Optional[str] = Field(default=None, max_length=4_000)


@router.get("")
async def list_approvals(
    db: Annotated[DbHandle, Depends(get_db_pool)],
    status_filter: ApprovalStatus = Query(default="pending", alias="status"),
    since: Optional[str] = Query(default=None, description="e.g. '24h' or '7 days'."),
) -> dict[str, Any]:
    """``pending`` shells to gate.sh; others read ``spine_lifecycle.approval``."""
    if status_filter == "pending":
        rc, out, err = _gate("list-pending")
        data = _parse_last_json(out)
        if rc != 0 or data is None:
            raise _err(502, "gate_error", err or "gate.sh produced no JSON")
        return data
    where = [f"decision = '{status_filter}'"]
    if since:
        s = since.strip()
        if s.endswith("h") and s[:-1].isdigit():
            s = f"{s[:-1]} hours"
        where.append(f"granted_at > NOW() - interval '{s.replace(chr(39), chr(39) * 2)}'")
    sql = (
        "SELECT json_build_object('approval_id', id::text, 'project_id', project_id::text, "
        "'phase', phase, 'approver', approver, 'decision', decision, 'notes', notes, "
        "'granted_at', granted_at, 'expires_at', expires_at)::text "
        f"FROM spine_lifecycle.approval WHERE {' AND '.join(where)} "
        "ORDER BY granted_at DESC LIMIT 200;"
    )
    try:
        rows = await db.fetch(sql)
    except RuntimeError as exc:
        raise _err(502, "db_error", str(exc)) from exc
    return {"ok": True, "items": [r["_row"] for r in rows], "status": status_filter}


@router.post("", status_code=status.HTTP_201_CREATED)
async def post_approval(
    body: ApprovalDecision,
    user: Annotated[User, Depends(current_user)],
) -> dict[str, Any]:
    """Record an approve / reject / request_changes decision via ``gate.sh``."""
    actor = body.approver or actor_label(user)
    if body.action == "approve":
        args = ["approve", body.project_id, actor] + ([body.notes] if body.notes else [])
    elif body.action == "reject":
        if not body.notes:
            raise _err(400, "invalid_input", "reason (notes) required for reject")
        args = ["reject", body.project_id, actor, body.notes]
    else:
        if not body.notes:
            raise _err(400, "invalid_input", "notes required for request_changes")
        args = ["request-changes", body.project_id, actor, body.notes]
    rc, out, err = _gate(*args)
    data = _parse_last_json(out) or {"ok": rc == 0, "stdout": out, "stderr": err}
    if rc != 0:
        raise _err(502, "gate_error", err.strip() or "gate.sh failed",
                   details={"rc": rc, "response": data})
    return data | {"actor": actor}


@router.get("/{approval_id}")
async def get_approval(
    approval_id: str,
    db: Annotated[DbHandle, Depends(get_db_pool)],
) -> dict[str, Any]:
    """Single approval row by surrogate ``id``."""
    if not approval_id.isdigit():
        raise _err(400, "invalid_input", "approval_id must be a positive integer")
    sql = (
        "SELECT json_build_object('approval_id', id::text, 'project_id', project_id::text, "
        "'phase', phase, 'artifact_ref', artifact_ref, 'approver', approver, "
        "'decision', decision, 'notes', notes, 'granted_at', granted_at, "
        "'expires_at', expires_at)::text "
        f"FROM spine_lifecycle.approval WHERE id = {approval_id};"
    )
    try:
        rows = await db.fetch(sql)
    except RuntimeError as exc:
        raise _err(502, "db_error", str(exc)) from exc
    if not rows:
        raise _err(404, "approval_not_found", f"no approval with id={approval_id}")
    return {"ok": True, "approval": rows[0]["_row"]}
