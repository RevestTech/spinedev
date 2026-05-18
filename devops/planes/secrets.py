"""Secret rotation control plane (V3 #11; ENUM ``secrets``).

Delegates value lookups to :mod:`shared.secrets` per design decision #9.
The Operate plane only schedules + audits rotations / access audits /
lease listings; it never touches secret values directly except through
``shared.secrets``'s async adapter API.

Supported actions
-----------------
* ``rotate`` — rotate a secret path (Cite-or-Refuse required).
* ``audit_access`` — emit an access-history report for a path.
* ``list_active_leases`` — list dynamic leases (Vault dynamic engines).
"""

from __future__ import annotations

from typing import Any

from devops.planes.base import ControlPlane, PlaneName, utcnow_iso


class SecretsControlPlane(ControlPlane):
    """Secret rotation plane — consumes :mod:`shared.secrets`."""

    name: PlaneName = "secrets"

    @classmethod
    def _supported_actions(cls) -> tuple[str, ...]:
        return ("rotate", "audit_access", "list_active_leases")

    async def _handle_action(
        self, action: str, payload: dict[str, Any],
    ) -> dict[str, Any]:
        # ``rotate`` is HIGH_IMPACT — Cite-or-Refuse will require evidence
        # ("previous value hash" + "rotation policy doc") before the
        # dispatcher will execute.
        if action == "rotate":
            raise NotImplementedError(
                "secrets.rotate — v1.1+ (Wave 3 rotation policy engine)"
            )
        if action == "audit_access":
            # Read-only stub: shape of the future report.
            return {
                "_stub": True,
                "secret_path": payload.get("secret_path"),
                "access_events": [],
                "report_generated_at": utcnow_iso(),
            }
        if action == "list_active_leases":
            return {
                "_stub": True,
                "active_leases": [],
                "checked_at": utcnow_iso(),
            }
        raise NotImplementedError(f"unsupported secrets action {action!r}")


__all__: list[str] = ["SecretsControlPlane"]
