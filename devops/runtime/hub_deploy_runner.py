"""Hub devops deploy runner — orchestrator entry for local container deploy."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

logger = logging.getLogger("spine.devops.hub_deploy")


@dataclass
class HubDeployResult:
    ok: bool
    directive_id: str
    role: str = "devops_release"
    deploy_target: str = "container"
    error_class: str | None = None
    error_message: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _load_project_dict(project_id: str) -> dict[str, Any]:
    from build.runtime.build_dispatcher import _load_project  # noqa: PLC0415

    row = _load_project(project_id)
    metadata = row.get("metadata") or {}
    if isinstance(metadata, str):
        import json

        metadata = json.loads(metadata or "{}")
    return {
        "id": row["id"],
        "project_uuid": row["project_uuid"],
        "name": row["name"],
        "current_phase": row.get("current_phase"),
        "metadata": metadata,
    }


async def run_local_deploy_async(project: dict[str, Any]) -> HubDeployResult:
    """Delegate to existing Hub local deploy implementation in ``_post_ack``."""
    directive_id = f"dir_{uuid4().hex[:12]}"
    try:
        from shared.api.routes._post_ack import _dispatch_local_deploy  # noqa: PLC0415

        await _dispatch_local_deploy(project=project)
    except Exception as exc:  # noqa: BLE001
        logger.exception("hub_deploy_failed")
        return HubDeployResult(
            ok=False,
            directive_id=directive_id,
            error_class=type(exc).__name__,
            error_message=str(exc)[:500],
        )
    return HubDeployResult(
        ok=True,
        directive_id=directive_id,
        extra={"deploy_target": "container"},
    )


def _run_local_deploy_on_hub_loop(project: dict[str, Any]) -> HubDeployResult:
    """Run local deploy on the Hub lifespan loop (safe for asyncpg pool)."""
    from shared.api.dependencies import get_hub_event_loop  # noqa: PLC0415

    hub_loop = get_hub_event_loop()
    if hub_loop is not None and hub_loop.is_running():
        future = asyncio.run_coroutine_threadsafe(
            run_local_deploy_async(project),
            hub_loop,
        )
        try:
            return future.result(timeout=600)
        except Exception as exc:  # noqa: BLE001
            logger.exception("hub_deploy_threadsafe_failed")
            return HubDeployResult(
                ok=False,
                directive_id=f"dir_{uuid4().hex[:12]}",
                error_class=type(exc).__name__,
                error_message=str(exc)[:500],
            )
    return asyncio.run(run_local_deploy_async(project))


def run_devops_hub_role(
    *,
    project_id: str,
    role: str,
    directive: str,
    actor: str = "orchestrator",
) -> HubDeployResult:
    """Sync MCP entry for devops release deploy directives."""
    _ = (role, actor)
    upper = directive.upper()
    project = _load_project_dict(project_id)

    if "DEPLOY" in upper or "LOCAL" in upper or "RELEASE" in upper:
        return _run_local_deploy_on_hub_loop(project)

    return HubDeployResult(
        ok=False,
        directive_id=f"dir_{uuid4().hex[:12]}",
        error_class="unsupported_directive",
        error_message=f"devops hub runner does not support directive={directive!r}",
    )


__all__ = ["HubDeployResult", "run_devops_hub_role"]
