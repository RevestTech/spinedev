"""Background role worker — directive queue poller (SPINE-005).

Polls two directive buses:

1. **File bus** — ``.spine/work/<project_uuid>/directives/*/status.json`` with
   ``pending`` or stale ``running`` (no ``report.md``).
2. **DB bus** — ``spine_lifecycle.portfolio_queue`` rows with
   ``dispatched_at IS NULL`` (overflow from ``portfolio.sh``).

Picked directives dispatch through the same MCP surface as the orchestrator
bridge (``plan_dispatch`` / ``build_dispatch`` / ``verify_hub_review``).

Enabled when ``SPINE_ROLE_WORKER=1``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger("spine.runtime.role_worker")

_POLL_SECS = float(os.environ.get("SPINE_ROLE_WORKER_POLL_SECS", "15"))
_STALE_RUNNING_SECS = float(os.environ.get("SPINE_ROLE_WORKER_STALE_SECS", "600"))
_DEFAULT_MAX_PARALLEL = int(os.environ.get("SPINE_DEFAULT_MAX_PARALLEL", "3"))

_SUBSYSTEM_TOOLS: dict[str, str] = {
    "plan": "plan_dispatch",
    "build": "build_dispatch",
    "verify": "verify_hub_review",
}

_PLAN_ROLES = frozenset({
    "product", "planner", "architect", "conductor", "qa", "release_manager",
})
_BUILD_ROLES = frozenset({
    "engineer", "devops", "devops_release", "auditor", "security_engineer",
})

QueueSource = Literal["file", "db"]


@dataclass(frozen=True)
class QueuedDirective:
    source: QueueSource
    project_id: str
    role: str
    directive: str
    subsystem: str
    actor: str = "role_worker"
    queue_id: int | None = None
    workspace: Path | None = None
    extra_context: str = ""


def _subsystem_for_role(role: str) -> str | None:
    if role in _PLAN_ROLES:
        return "plan"
    if role in _BUILD_ROLES:
        return "build"
    return None


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_stale_running(meta: dict[str, Any], workspace: Path) -> bool:
    if meta.get("status") != "running":
        return False
    if (workspace / "report.md").is_file():
        return False
    started = _parse_ts(str(meta.get("started_at") or meta.get("queued_at") or ""))
    if started is None:
        return True
    age = (datetime.now(timezone.utc) - started).total_seconds()
    return age >= _STALE_RUNNING_SECS


def scan_file_directives(root: Path | None = None) -> list[QueuedDirective]:
    """Return pending or stale-running directives from the file bus."""
    from shared.runtime.role_runtime import directives_root  # noqa: PLC0415

    work_root = root or directives_root()
    if not work_root.is_dir():
        return []

    found: list[QueuedDirective] = []
    for project_dir in sorted(work_root.iterdir()):
        if not project_dir.is_dir():
            continue
        directives_dir = project_dir / "directives"
        if not directives_dir.is_dir():
            continue
        for ws in sorted(directives_dir.iterdir()):
            if not ws.is_dir():
                continue
            status_path = ws / "status.json"
            if not status_path.is_file():
                continue
            try:
                meta = json.loads(status_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            status = str(meta.get("status") or "")
            if status == "pending" or _is_stale_running(meta, ws):
                role = str(meta.get("role") or "")
                subsystem = _subsystem_for_role(role)
                if subsystem is None:
                    continue
                found.append(QueuedDirective(
                    source="file",
                    project_id=str(meta.get("project_uuid") or project_dir.name),
                    role=role,
                    directive=str(meta.get("directive") or ""),
                    subsystem=subsystem,
                    actor=str(meta.get("actor") or "role_worker"),
                    workspace=ws,
                ))
    return found


async def scan_db_directives() -> list[QueuedDirective]:
    """Return undispatched rows from ``spine_lifecycle.portfolio_queue``."""
    from shared.api.dependencies import get_db_pool_raw  # noqa: PLC0415

    pool = get_db_pool_raw()
    if pool is None:
        return []

    sql = """
    SELECT q.id,
           q.subsystem,
           q.role,
           q.directive_payload,
           p.project_uuid::text AS project_uuid
    FROM spine_lifecycle.portfolio_queue q
    JOIN spine_lifecycle.project p ON p.id = q.project_id
    WHERE q.dispatched_at IS NULL
    ORDER BY q.priority ASC, q.queued_at ASC
    LIMIT 20
    """
    rows: list[QueuedDirective] = []
    async with pool.acquire() as conn:
        result = await conn.fetch(sql)
    for row in result:
        payload = row["directive_payload"]
        if isinstance(payload, str):
            payload = json.loads(payload or "{}")
        directive = str(
            (payload or {}).get("directive")
            or (payload or {}).get("directive_ref")
            or row["role"]
        )
        subsystem = str(row["subsystem"])
        if subsystem not in _SUBSYSTEM_TOOLS:
            continue
        rows.append(QueuedDirective(
            source="db",
            project_id=str(row["project_uuid"]),
            role=str(row["role"]),
            directive=directive,
            subsystem=subsystem,
            queue_id=int(row["id"]),
        ))
    return rows


async def _project_db_id(project_uuid: str) -> int | None:
    from shared.api.dependencies import get_db_pool_raw  # noqa: PLC0415

    pool = get_db_pool_raw()
    if pool is None:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM spine_lifecycle.project WHERE project_uuid::text = $1",
            project_uuid,
        )
    return int(row["id"]) if row else None


async def _can_dispatch_project(project_uuid: str) -> bool:
    """Mirror ``portfolio_can_dispatch`` headroom check."""
    from shared.api.dependencies import get_db_pool_raw  # noqa: PLC0415

    pool = get_db_pool_raw()
    if pool is None:
        return True

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT p.status,
                   COALESCE((p.metadata->>'blocked')::bool, false) AS blocked,
                   COALESCE((p.metadata->>'max_parallel_directives')::int, $2) AS lim,
                   (SELECT COUNT(*) FROM spine_lifecycle.route_history rh
                     WHERE rh.project_id = p.id AND rh.completed_at IS NULL) AS in_flight
            FROM spine_lifecycle.project p
            WHERE p.project_uuid::text = $1
            """,
            project_uuid,
            _DEFAULT_MAX_PARALLEL,
        )
    if row is None:
        return False
    if row["status"] == "paused" or row["blocked"]:
        return False
    return int(row["in_flight"]) < int(row["lim"])


def _claim_file_directive(workspace: Path) -> bool:
    status_path = workspace / "status.json"
    try:
        meta = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if meta.get("status") not in ("pending", "running"):
        return False
    meta["status"] = "running"
    meta["started_at"] = datetime.now(timezone.utc).isoformat()
    meta["claimed_by"] = "role_worker"
    status_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return True


def _finish_file_directive(workspace: Path, *, ok: bool, detail: str = "") -> None:
    status_path = workspace / "status.json"
    try:
        meta = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    meta["status"] = "done" if ok else "failed"
    meta["finished_at"] = datetime.now(timezone.utc).isoformat()
    if detail:
        meta["worker_detail"] = detail[:500]
    status_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    if detail:
        (workspace / "report.md").write_text(detail.strip() + "\n", encoding="utf-8")


async def _mark_db_dispatched(queue_id: int) -> None:
    from shared.api.dependencies import get_db_pool_raw  # noqa: PLC0415

    pool = get_db_pool_raw()
    if pool is None:
        return
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE spine_lifecycle.portfolio_queue SET dispatched_at = NOW() WHERE id = $1",
            queue_id,
        )


async def _load_pipeline_version(project_id: str) -> str:
    from shared.api.dependencies import get_db_pool_raw  # noqa: PLC0415

    pool = get_db_pool_raw()
    if pool is None:
        return os.environ.get("SPINE_PIPELINE_VERSION", "1")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COALESCE(pipeline_version, '1') AS pv "
            "FROM spine_lifecycle.project WHERE project_uuid::text = $1",
            project_id,
        )
    return str(row["pv"]) if row else "1"


def _build_mcp_payload(item: QueuedDirective, pipeline_version: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "project_id": item.project_id,
        "role": item.role,
        "directive": item.directive,
        "pipeline_version": pipeline_version,
        "actor": item.actor,
    }
    if item.subsystem == "plan":
        payload["phase"] = "plan_in_progress"
    if item.extra_context:
        payload["extra_context"] = item.extra_context
    return payload


async def dispatch_queued_directive(item: QueuedDirective) -> bool:
    """Dispatch one queued directive via MCP. Returns True on success."""
    from shared.runtime.mcp_invoke import invoke_mcp_tool  # noqa: PLC0415

    tool = _SUBSYSTEM_TOOLS.get(item.subsystem)
    if not tool:
        logger.warning(
            "role_worker_unknown_subsystem",
            extra={"subsystem": item.subsystem, "role": item.role},
        )
        return False

    if item.source == "file" and item.workspace is not None:
        if not _claim_file_directive(item.workspace):
            return False

    if item.source == "db":
        if not await _can_dispatch_project(item.project_id):
            return False

    pipeline_version = await _load_pipeline_version(item.project_id)
    payload = _build_mcp_payload(item, pipeline_version)

    logger.info(
        "role_worker_dispatch",
        extra={
            "source": item.source,
            "project_id": item.project_id,
            "role": item.role,
            "tool": tool,
            "queue_id": item.queue_id,
        },
    )

    raw = await asyncio.to_thread(invoke_mcp_tool, tool, payload)
    status = raw.get("status")
    data = raw.get("data") or {}
    err_obj = raw.get("error") or {}
    err_msg = err_obj.get("message") if isinstance(err_obj, dict) else str(err_obj)
    ok = status == "ok"

    if item.source == "file" and item.workspace is not None:
        detail = (
            f"# Worker dispatch\n\n"
            f"- **Tool:** {tool}\n"
            f"- **OK:** {ok}\n"
        )
        if err_msg:
            detail += f"- **Error:** {err_msg}\n"
        _finish_file_directive(item.workspace, ok=ok, detail=detail)

    if item.source == "db" and item.queue_id is not None and ok:
        await _mark_db_dispatched(item.queue_id)

    if not ok:
        logger.warning(
            "role_worker_dispatch_failed",
            extra={
                "project_id": item.project_id,
                "role": item.role,
                "error": err_msg or "dispatch failed",
            },
        )
    return ok


async def role_worker_tick() -> int:
    """One poll cycle. Returns count of successful dispatches."""
    file_items = scan_file_directives()
    db_items = await scan_db_directives()
    dispatched = 0
    for item in file_items + db_items:
        try:
            if await dispatch_queued_directive(item):
                dispatched += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "role_worker_item_failed",
                extra={
                    "project_id": item.project_id,
                    "role": item.role,
                    "error": str(exc),
                },
            )
            if item.source == "file" and item.workspace is not None:
                _finish_file_directive(
                    item.workspace,
                    ok=False,
                    detail=f"# Worker error\n\n{exc}\n",
                )
    return dispatched


async def run_role_worker(stop: asyncio.Event) -> None:
    """Background loop until ``stop`` is set."""
    logger.info("role_worker_started", extra={"poll_secs": _POLL_SECS})
    while not stop.is_set():
        try:
            count = await role_worker_tick()
            if count:
                logger.info("role_worker_tick", extra={"dispatched": count})
        except Exception as exc:  # noqa: BLE001
            logger.warning("role_worker_tick_failed", extra={"error": str(exc)})
        try:
            await asyncio.wait_for(stop.wait(), timeout=_POLL_SECS)
        except asyncio.TimeoutError:
            continue
    logger.info("role_worker_stopped")


def worker_enabled() -> bool:
    raw = os.environ.get("SPINE_ROLE_WORKER", "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


__all__ = [
    "QueuedDirective",
    "dispatch_queued_directive",
    "role_worker_tick",
    "run_role_worker",
    "scan_db_directives",
    "scan_file_directives",
    "worker_enabled",
]
