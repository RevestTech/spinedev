"""Eight control plane modules for the Operate subsystem (V3 #11).

Each plane corresponds to one value of ``spine_devops.control_plane_name``
(see ``db/flyway/sql/V27__devops_role.sql``):

================= ===========================================================
ENUM value        Module
================= ===========================================================
``ci_cd``         :mod:`devops.planes.ci_cd`
``infrastructure``:mod:`devops.planes.infrastructure`
``secrets``       :mod:`devops.planes.secrets`
``monitoring``    :mod:`devops.planes.monitoring`
``alerting``      :mod:`devops.planes.alerting`
``deployment``    :mod:`devops.planes.deployment`
``database``      :mod:`devops.planes.database`
``networking``    :mod:`devops.planes.networking`
================= ===========================================================

Each plane sub-classes :class:`devops.planes.base.ControlPlane` and exposes:

* ``name`` — string matching the ENUM value above.
* ``async status(project_id)`` -> :class:`PlaneStatus`.
* ``async invoke(action, payload)`` -> :class:`ActionResult` — audit-logs
  the call via :func:`shared.audit.audit_record.AuditRecord`.
* ``classmethod supported_actions()`` -> list of action names.

For v1.0 the deeper action handlers raise ``NotImplementedError("v1.1+")``;
the **framework + registry + audit wiring is real** so Wave 3 can drop in
real implementations one action at a time.
"""

from __future__ import annotations

from devops.planes.alerting import AlertingControlPlane
from devops.planes.base import (
    ActionResult,
    ControlPlane,
    PlaneStatus,
    HIGH_IMPACT_ACTIONS,
)
from devops.planes.ci_cd import CIControlPlane
from devops.planes.database import DatabaseControlPlane
from devops.planes.deployment import DeploymentControlPlane
from devops.planes.infrastructure import InfrastructureControlPlane
from devops.planes.monitoring import MonitoringControlPlane
from devops.planes.networking import NetworkingControlPlane
from devops.planes.secrets import SecretsControlPlane

__all__: list[str] = [
    # Base + types
    "ActionResult",
    "ControlPlane",
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
