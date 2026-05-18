"""Database ops control plane (V3 #11; ENUM ``database``).

Owns Flyway migrations, backup orchestration, restore-verification, and
slow-query reporting. ``migrate`` and ``restore_test`` are HIGH_IMPACT
(Cite-or-Refuse-required per #12).

Supported actions
-----------------
* ``migrate`` — apply Flyway migrations forward (Cite-or-Refuse).
* ``backup`` — trigger a logical / physical backup.
* ``restore_test`` — restore-to-throwaway verification (Cite-or-Refuse).
* ``slow_query_report`` — surface the recent slow-query log.
"""

from __future__ import annotations

from typing import Any

from devops.planes.base import ControlPlane, PlaneName, utcnow_iso


class DatabaseControlPlane(ControlPlane):
    """DB ops plane — Flyway / backup / restore-test scaffold."""

    name: PlaneName = "database"

    @classmethod
    def _supported_actions(cls) -> tuple[str, ...]:
        return ("migrate", "backup", "restore_test", "slow_query_report")

    async def _handle_action(
        self, action: str, payload: dict[str, Any],
    ) -> dict[str, Any]:
        if action == "slow_query_report":
            return {
                "_stub": True,
                "queries": [],
                "window_seconds": payload.get("window_seconds", 3600),
                "generated_at": utcnow_iso(),
            }
        if action == "backup":
            return {
                "_stub": True,
                "backup_id": payload.get("backup_id"),
                "target_uri": payload.get("target_uri"),
                "queued_at": utcnow_iso(),
            }
        if action in ("migrate", "restore_test"):
            raise NotImplementedError(
                f"database.{action} — v1.1+ (Wave 3 Flyway/DR plumbing)"
            )
        raise NotImplementedError(f"unsupported database action {action!r}")


__all__: list[str] = ["DatabaseControlPlane"]
