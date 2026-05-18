"""Infrastructure (IaC) control plane (V3 #11; ENUM ``infrastructure``).

Scaffolds for **Terraform / Pulumi**. ``apply`` and ``destroy`` are
HIGH_IMPACT (Cite-or-Refuse-required per #12).

Supported actions
-----------------
* ``plan`` — dry-run; show diff.
* ``apply`` — execute the plan (Cite-or-Refuse required).
* ``destroy`` — tear down (Cite-or-Refuse required).
* ``drift_detect`` — compare actual vs declared state.
* ``cost_estimate`` — Infracost-style projection of the plan.
"""

from __future__ import annotations

from typing import Any

from devops.planes.base import ControlPlane, PlaneName, utcnow_iso


class InfrastructureControlPlane(ControlPlane):
    """IaC plane — Terraform / Pulumi scaffold."""

    name: PlaneName = "infrastructure"

    @classmethod
    def _supported_actions(cls) -> tuple[str, ...]:
        return ("plan", "apply", "destroy", "drift_detect", "cost_estimate")

    async def _handle_action(
        self, action: str, payload: dict[str, Any],
    ) -> dict[str, Any]:
        # Read-only paths can stub a synthetic empty result.
        if action == "plan":
            return {
                "_stub": True,
                "provider": payload.get("provider", "terraform"),
                "workspace": payload.get("workspace"),
                "changes": {"add": 0, "change": 0, "destroy": 0},
                "planned_at": utcnow_iso(),
            }
        if action == "drift_detect":
            return {
                "_stub": True,
                "drift_resources": [],
                "checked_at": utcnow_iso(),
            }
        if action == "cost_estimate":
            return {
                "_stub": True,
                "monthly_usd": 0.0,
                "estimated_at": utcnow_iso(),
            }
        if action in ("apply", "destroy"):
            raise NotImplementedError(
                f"infrastructure.{action} — v1.1+ (Wave 3 IaC plumbing)"
            )
        raise NotImplementedError(
            f"unsupported infrastructure action {action!r}"
        )


__all__: list[str] = ["InfrastructureControlPlane"]
