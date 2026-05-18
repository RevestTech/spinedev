"""Deployment / release control plane (V3 #11; ENUM ``deployment``).

Release-management surface: deploy, rollback, canary promotion, and
feature-flag toggles. ``deploy``, ``rollback``, and ``canary`` are
HIGH_IMPACT (Cite-or-Refuse-required per #12).

Supported actions
-----------------
* ``deploy`` — push a build to an env (Cite-or-Refuse required).
* ``rollback`` — revert to the previous release (Cite-or-Refuse).
* ``canary`` — promote / hold a canary slice (Cite-or-Refuse).
* ``feature_flag_toggle`` — flip a flag (audit-only, low blast radius).
"""

from __future__ import annotations

from typing import Any

from devops.planes.base import ControlPlane, PlaneName, utcnow_iso


class DeploymentControlPlane(ControlPlane):
    """Release plane — deploy / rollback / canary / flag scaffold."""

    name: PlaneName = "deployment"

    @classmethod
    def _supported_actions(cls) -> tuple[str, ...]:
        return ("deploy", "rollback", "canary", "feature_flag_toggle")

    async def _handle_action(
        self, action: str, payload: dict[str, Any],
    ) -> dict[str, Any]:
        if action == "feature_flag_toggle":
            return {
                "_stub": True,
                "flag": payload.get("flag"),
                "new_state": payload.get("new_state"),
                "toggled_at": utcnow_iso(),
            }
        if action in ("deploy", "rollback", "canary"):
            raise NotImplementedError(
                f"deployment.{action} — v1.1+ (Wave 3 release engine)"
            )
        raise NotImplementedError(f"unsupported deployment action {action!r}")


__all__: list[str] = ["DeploymentControlPlane"]
