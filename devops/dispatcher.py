"""DevOps dispatcher — registry of the 8 Operate control planes (V3 #11).

Single dispatch surface used by :mod:`devops.mcp_tools` (and Wave 3+
callers) to route ``(plane, action, payload)`` triples to the right
:class:`devops.planes.base.ControlPlane` instance.

The dispatcher owns:

* Plane registration (8 planes wired at construction).
* Action lookup → ``plane.invoke()``.
* Cite-or-Refuse pre-flight: any action whose name is in
  :data:`devops.planes.base.HIGH_IMPACT_ACTIONS` requires the caller to
  pass a non-empty ``citation`` list in the payload. When missing, the
  dispatcher refuses to dispatch and audit-logs the refusal (mirrors
  ``shared.mcp.cite_or_refuse``).

Why the dispatcher enforces the contract here (and the MCP middleware
re-enforces on the wire) — defence-in-depth per #12. The MCP middleware
catches calls that already returned without citation; the dispatcher
catches calls before they execute when the action is intrinsically
HIGH_IMPACT.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from devops.planes import (
    AlertingControlPlane,
    CIControlPlane,
    DatabaseControlPlane,
    DeploymentControlPlane,
    InfrastructureControlPlane,
    MonitoringControlPlane,
    NetworkingControlPlane,
    SecretsControlPlane,
)
from devops.planes.base import (
    ActionResult,
    ControlPlane,
    HIGH_IMPACT_ACTIONS,
    PlaneName,
    PlaneStatus,
)

logger = logging.getLogger(__name__)

#: All eight plane CLASSES — registration list. Order matters only for
#: deterministic iteration in tests.
_PLANE_CLASSES: tuple[type[ControlPlane], ...] = (
    CIControlPlane,
    InfrastructureControlPlane,
    SecretsControlPlane,
    MonitoringControlPlane,
    AlertingControlPlane,
    DeploymentControlPlane,
    DatabaseControlPlane,
    NetworkingControlPlane,
)


class DevOpsDispatcher:
    """Owns the 8-plane registry; routes action calls; enforces Cite-or-Refuse."""

    def __init__(self, *, actor: str = "devops") -> None:
        self._actor = actor
        self._planes: dict[str, ControlPlane] = {}
        for cls in _PLANE_CLASSES:
            self.register(cls(actor=actor))
        # Sanity: V27 says exactly 8 planes; dispatcher must mirror.
        if len(self._planes) != 8:
            raise RuntimeError(
                f"DevOpsDispatcher: expected 8 planes registered; got "
                f"{len(self._planes)}: {sorted(self._planes)}"
            )

    # -- Registry surface ---------------------------------------------

    def register(self, plane: ControlPlane) -> None:
        """Register a control plane instance under its ``name``."""
        if not isinstance(plane.name, str):
            raise TypeError(
                f"plane {type(plane).__name__} has invalid name {plane.name!r}"
            )
        if plane.name in self._planes:
            raise ValueError(
                f"plane name {plane.name!r} already registered by "
                f"{type(self._planes[plane.name]).__name__}"
            )
        self._planes[plane.name] = plane

    def registered_planes(self) -> list[str]:
        """Return the list of registered plane names."""
        return list(self._planes.keys())

    def get(self, plane_name: str) -> ControlPlane:
        """Resolve a plane by name; raises ``KeyError`` if unknown."""
        try:
            return self._planes[plane_name]
        except KeyError as exc:
            raise KeyError(
                f"unknown control plane {plane_name!r}; "
                f"registered: {sorted(self._planes)}"
            ) from exc

    def supported_actions(self, plane_name: str) -> list[str]:
        """Return ``plane_name``'s supported_actions list."""
        return self.get(plane_name).supported_actions()

    # -- Cite-or-Refuse classification --------------------------------

    @staticmethod
    def requires_citation(action: str) -> bool:
        """``True`` iff ``action`` is in :data:`HIGH_IMPACT_ACTIONS`."""
        return action in HIGH_IMPACT_ACTIONS

    # -- Dispatch -----------------------------------------------------

    async def status(self, plane_name: str, project_id: str | None = None) -> PlaneStatus:
        """Proxy to ``plane.status(project_id)``."""
        return await self.get(plane_name).status(project_id)

    async def invoke(
        self,
        plane_name: str,
        action: str,
        payload: dict[str, Any] | None = None,
    ) -> ActionResult:
        """Dispatch ``(plane_name, action, payload)`` with Cite-or-Refuse.

        For HIGH_IMPACT actions (``apply``, ``deploy``, ``rotate``,
        ``destroy``, ``rollback``, ``canary``, ``restore_test``,
        ``migrate``, ``ssl_cert_renew``, ``dns_update``) the payload
        MUST carry a non-empty ``citation`` list — otherwise we refuse
        the dispatch + record a refusal audit row mirroring
        ``shared.mcp.cite_or_refuse``.
        """
        payload = dict(payload or {})
        try:
            plane = self.get(plane_name)
        except KeyError as exc:
            return ActionResult(
                # type:ignore[arg-type] - we know plane_name is invalid here;
                # we still need *some* PlaneName for the envelope. Reuse
                # ci_cd as a placeholder so the Pydantic Literal accepts it
                # — error string makes the actual issue obvious.
                plane_name="ci_cd",
                action=action,
                status="error",
                error=str(exc),
            )

        if self.requires_citation(action):
            citation = payload.get("citation")
            if not isinstance(citation, list) or len(citation) == 0:
                self._record_refusal(
                    plane_name=plane_name, action=action, payload=payload,
                    reason="missing_or_empty_citation",
                )
                return ActionResult(
                    plane_name=plane.name,
                    action=action,
                    status="error",
                    error=(
                        "Cite-or-Refuse contract (V3 #12) violated: "
                        f"action {action!r} on plane {plane_name!r} is "
                        "HIGH_IMPACT and requires a non-empty 'citation' "
                        "list in the payload. Refusing to dispatch."
                    ),
                )

        return await plane.invoke(action, payload)

    # -- Internal helpers ---------------------------------------------

    def _record_refusal(
        self,
        *,
        plane_name: str,
        action: str,
        payload: dict[str, Any],
        reason: str,
    ) -> None:
        """Persist a refusal as a shared.audit row. Failures swallowed."""
        try:
            from shared.audit.audit_record import AuditRecord
        except Exception:  # pragma: no cover - audit pkg optional
            logger.warning(
                "devops dispatcher: audit_record import failed; "
                "skip refusal audit"
            )
            return
        try:
            project_id = payload.get("project_id")
            try:
                pid_int = int(project_id) if project_id is not None else None
            except (TypeError, ValueError):
                pid_int = None
            AuditRecord(
                role="devops",
                # Wave 3 (Squad A) — ALLOWED_SUBSYSTEMS now includes
                # ``devops``; V35 extends the matching DB CHECK.
                subsystem="devops",
                action="cite_or_refuse_refused",
                actor=self._actor,
                project_id=pid_int,
                subject_type="devops_action",
                subject_id=f"{plane_name}.{action}",
                rationale=(
                    "DevOps dispatcher refused HIGH_IMPACT action without "
                    "citation per V3 #12 (Cite-or-Refuse)."
                ),
                metadata={
                    "plane_name": plane_name,
                    "action": action,
                    "reason": reason,
                    "refusal_id": str(uuid4()),
                },
            )
        except Exception:  # pragma: no cover - defensive
            logger.exception("devops dispatcher: refusal audit build failed")


__all__: list[str] = ["DevOpsDispatcher"]
