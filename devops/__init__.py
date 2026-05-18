"""
devops — Operate subsystem (V3 #11).

The 6th corner of the Spine SDLC: customer-facing DevOps role + 8
control planes (W2 reframe of R7 research). Per design decision #11,
distinct from the Spine-internal ``operator`` role.

Top-level re-exports:

* :class:`DevOpsDispatcher` — central registry + dispatch surface.
* :class:`ControlPlane` — ABC every plane inherits.
* :class:`ActionResult` / :class:`PlaneStatus` — typed envelopes.
* 8 concrete plane classes (``CIControlPlane``, ``InfrastructureControlPlane``,
  ``SecretsControlPlane``, ``MonitoringControlPlane``,
  ``AlertingControlPlane``, ``DeploymentControlPlane``,
  ``DatabaseControlPlane``, ``NetworkingControlPlane``).

MCP tools (``devops_invoke``, ``devops_status``, ``devops_planes_list``)
live in :mod:`devops.mcp_tools` and auto-register via the existing
``@register_tool`` decorator on import.

See ``devops/README.md`` for the relationship to:
  * ``shared/charters/devops.md`` (Squad 1) — the role charter.
  * ``db/flyway/sql/V27__devops_role.sql`` — the DB layer (schema +
    ``control_plane_name`` ENUM + ``action_log`` + ``runbook`` tables).
"""

from __future__ import annotations

from devops.dispatcher import DevOpsDispatcher
from devops.planes import (
    ActionResult,
    AlertingControlPlane,
    CIControlPlane,
    ControlPlane,
    DatabaseControlPlane,
    DeploymentControlPlane,
    HIGH_IMPACT_ACTIONS,
    InfrastructureControlPlane,
    MonitoringControlPlane,
    NetworkingControlPlane,
    PlaneStatus,
    SecretsControlPlane,
)

__all__: list[str] = [
    # Dispatcher
    "DevOpsDispatcher",
    # Base
    "ControlPlane",
    "ActionResult",
    "PlaneStatus",
    "HIGH_IMPACT_ACTIONS",
    # 8 concrete planes
    "CIControlPlane",
    "InfrastructureControlPlane",
    "SecretsControlPlane",
    "MonitoringControlPlane",
    "AlertingControlPlane",
    "DeploymentControlPlane",
    "DatabaseControlPlane",
    "NetworkingControlPlane",
]
