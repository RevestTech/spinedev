"""CI/CD control plane (V3 #11; ENUM value ``ci_cd``).

Scaffolds for **GitHub Actions / GitLab CI / Jenkins**. Wave-3 squads will
flesh out the actual provider integrations; the framework + registry +
audit wiring is real today.

Supported actions
-----------------
* ``trigger_build`` — kick a pipeline run.
* ``cancel_build`` — abort an in-flight run.
* ``retry_build`` — re-run a failed build (same ref + env).
* ``status_check`` — last-known status for a run id.
"""

from __future__ import annotations

from typing import Any

from devops.planes.base import ControlPlane, PlaneName, utcnow_iso


class CIControlPlane(ControlPlane):
    """CI/CD plane — GH Actions / GitLab CI / Jenkins scaffold."""

    name: PlaneName = "ci_cd"

    @classmethod
    def _supported_actions(cls) -> tuple[str, ...]:
        return ("trigger_build", "cancel_build", "retry_build", "status_check")

    async def _handle_action(
        self, action: str, payload: dict[str, Any],
    ) -> dict[str, Any]:
        # v1.0 stubs — Wave 3 plumbs provider SDKs (PyGithub / python-
        # gitlab / jenkinsapi) through a per-project provider selector.
        if action == "status_check":
            # Read-only path can return a synthetic "unknown" so consumers
            # don't crash on a fresh deployment.
            return {
                "_stub": True,
                "provider": payload.get("provider", "github_actions"),
                "run_id": payload.get("run_id"),
                "state": "unknown",
                "checked_at": utcnow_iso(),
            }
        if action in ("trigger_build", "cancel_build", "retry_build"):
            raise NotImplementedError(
                f"ci_cd.{action} — v1.1+ (Wave 3 provider plumbing)"
            )
        # Defensive — base.invoke() validates first, but keep the door
        # closed in case of direct calls.
        raise NotImplementedError(f"unsupported ci_cd action {action!r}")


__all__: list[str] = ["CIControlPlane"]
