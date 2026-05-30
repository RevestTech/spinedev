"""Operate-phase runner (D2 slate #5 — closes released → operate).

Iterates the eight V3 #11 control planes, gathers a status snapshot
from each, and emits a V3 #30a envelope that downstream
``operate_kickoff`` consumers (per slate #4 watcher rule) treat as
the project's transition into Operate.

Design notes
------------

* **Minimal slate-closer.** Per D2: only one plane needs to be fully
  wired and seven can be stubbed for the loop to advance. The real
  per-plane health logic continues to live in ``devops/planes/*``;
  this runner orchestrates them via the existing ``ControlPlane``
  ABC.
* **Fail-soft.** A plane that raises on ``.status()`` is recorded as
  ``error`` in its slot but does NOT block the operate transition —
  the orchestrator surfaces the report and lets the operator decide.
* **Provider-agnostic.** This module never calls an LLM. Real
  remediation lives in the plane modules' ``invoke()`` paths; the
  runner is read-only.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import uuid4

from shared.mcp.schemas import Artifact, ToolError, ToolResponse

logger = logging.getLogger("spine.devops.operate_runner")


# Module-level constant so tests + callers see the same plane order.
PLANE_NAMES: tuple[str, ...] = (
    "infrastructure",
    "deployment",
    "monitoring",
    "alerting",
    "networking",
    "database",
    "secrets",
    "ci_cd",
)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _gather_plane_statuses(
    project_uuid: str,
    plane_names: Iterable[str],
) -> list[dict[str, Any]]:
    """Best-effort fan-out over the eight control planes."""
    statuses: list[dict[str, Any]] = []
    for name in plane_names:
        try:
            cls = _load_plane_class(name)
            instance = cls()
            snapshot = await instance.status(project_uuid)
            statuses.append(_status_to_dict(name, snapshot))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "operate_runner_plane_error",
                extra={"plane": name, "error": str(exc)[:200]},
            )
            statuses.append({
                "plane": name,
                "status": "error",
                "error": f"{exc.__class__.__name__}: {exc}",
                "checked_at": _utcnow_iso(),
            })
    return statuses


def _load_plane_class(plane_name: str):
    """Resolve ``devops.planes.<name>.<Name>ControlPlane`` lazily."""
    import importlib

    module = importlib.import_module(f"devops.planes.{plane_name}")
    # Camel-case naming with the project's "control_plane" suffix.
    parts = "".join(word.capitalize() for word in plane_name.split("_"))
    cls_name = f"{parts}ControlPlane"
    return getattr(module, cls_name)


def _status_to_dict(plane: str, snapshot: Any) -> dict[str, Any]:
    """Normalise PlaneStatus (Pydantic) into a JSONable shape."""
    if hasattr(snapshot, "model_dump"):
        body = snapshot.model_dump()
        return {
            "plane": plane,
            "status": body.get("status", "unknown"),
            "metadata": {
                k: v for k, v in body.items()
                if k not in {"plane_name", "status"}
            },
            "checked_at": _utcnow_iso(),
        }
    return {
        "plane": plane,
        "status": "unknown",
        "metadata": {"raw": str(snapshot)[:200]},
        "checked_at": _utcnow_iso(),
    }


def _summarise(statuses: list[dict[str, Any]]) -> tuple[str, str]:
    """Return (top-level status, summary text)."""
    error_planes = [s["plane"] for s in statuses if s["status"] == "error"]
    active = sum(1 for s in statuses if s["status"] == "active")
    if error_planes:
        return (
            "warning",
            f"operate: {active}/{len(statuses)} planes active; "
            f"errors on {', '.join(error_planes)}",
        )
    return (
        "ok",
        f"operate: {active}/{len(statuses)} planes active; loop entered operate phase",
    )


def run_operate(
    project: dict[str, Any],
    *,
    plane_names: Iterable[str] | None = None,
    status_runner: Any = None,
) -> ToolResponse:
    """Synchronous entry point — runs the async fan-out internally.

    Returns a V3 #30a envelope:

      * ``status='ok'`` if every plane reports a non-error status.
      * ``status='warning'`` if any plane errored; operate still
        proceeds — the orchestrator surfaces the report.
      * ``status='error'`` only for input failures (e.g. missing
        project_uuid). Never wraps a plane-side error as ``error``;
        those become ``warning``.
    """
    project_uuid = str(project.get("project_uuid", "")).strip()
    project_name = str(project.get("name", "")).strip() or "(unknown)"
    if not project_uuid:
        return ToolResponse(
            status="error",
            summary="operate: refused — missing project_uuid",
            data={"project_name": project_name},
            error=ToolError(
                code="missing_project_uuid",
                message="run_operate requires project.project_uuid",
                retryable=False,
            ),
        )

    names = tuple(plane_names) if plane_names is not None else PLANE_NAMES

    if status_runner is not None:
        statuses = status_runner(project_uuid, names)
    else:
        try:
            statuses = asyncio.run(
                _gather_plane_statuses(project_uuid, names),
            )
        except RuntimeError:
            # Already inside a loop — caller should provide
            # status_runner instead.
            return ToolResponse(
                status="error",
                summary="operate: refused — caller in an event loop",
                error=ToolError(
                    code="event_loop_active",
                    message=(
                        "run_operate cannot use asyncio.run inside a "
                        "running loop; pass status_runner for the async "
                        "fan-out"
                    ),
                    retryable=False,
                ),
            )

    top_status, summary = _summarise(statuses)
    run_id = f"operate_{uuid4().hex[:12]}"
    started_at = _utcnow_iso()

    return ToolResponse(
        status=top_status,
        summary=summary,
        next_actions=[
            "phase_watcher will advance released → operate on this entry",
            "review the operate_report for any plane in 'error'",
        ],
        artifacts=[
            Artifact(
                type="run_id",
                ref=run_id,
                label=f"operate snapshot for {project_name}",
            ),
        ],
        data={
            "project_uuid": project_uuid,
            "project_name": project_name,
            "operate_started_at": started_at,
            "operate_report": {
                "planes": statuses,
                "plane_count": len(statuses),
            },
        },
    )


__all__ = ["PLANE_NAMES", "run_operate"]
