"""Alerting / on-call control plane (V3 #11; ENUM ``alerting``).

Scaffolds for **PagerDuty / Slack** via :mod:`shared.notify`. The
plane only owns *routing*; channel credentials live in
:mod:`shared.secrets`.

Supported actions
-----------------
* ``route`` — route a fired alert to the right on-call.
* ``ack`` — acknowledge an in-flight incident.
* ``escalate`` — escalate to the next on-call tier.
* ``silence`` — temporarily silence an alert pattern.
"""

from __future__ import annotations

from typing import Any

from devops.planes.base import ControlPlane, PlaneName, utcnow_iso


class AlertingControlPlane(ControlPlane):
    """Alerting plane — PagerDuty / Slack routing scaffold."""

    name: PlaneName = "alerting"

    @classmethod
    def _supported_actions(cls) -> tuple[str, ...]:
        return ("route", "ack", "escalate", "silence")

    async def _handle_action(
        self, action: str, payload: dict[str, Any],
    ) -> dict[str, Any]:
        if action == "silence":
            return {
                "_stub": True,
                "silence_id": payload.get("silence_id"),
                "until": payload.get("until"),
                "created_at": utcnow_iso(),
            }
        if action in ("route", "ack", "escalate"):
            raise NotImplementedError(
                f"alerting.{action} — v1.1+ (Wave 3 routing engine)"
            )
        raise NotImplementedError(f"unsupported alerting action {action!r}")


__all__: list[str] = ["AlertingControlPlane"]
