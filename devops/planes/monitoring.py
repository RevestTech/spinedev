"""Monitoring / metrics + dashboards control plane (V3 #11; ENUM ``monitoring``).

Scaffolds for Prometheus / Grafana / Datadog / New Relic; the Wave-3
backend selects per-project provider via bundle config.

Supported actions
-----------------
* ``add_dashboard`` — provision a dashboard from a templated JSON.
* ``query`` — execute a PromQL / DDQL / NRQL query.
* ``alert_define`` — define a new alert rule.
* ``sli_track`` — register a new SLI/SLO for ongoing tracking.
"""

from __future__ import annotations

from typing import Any

from devops.planes.base import ControlPlane, PlaneName, utcnow_iso


class MonitoringControlPlane(ControlPlane):
    """Monitoring plane — metrics + dashboards scaffold."""

    name: PlaneName = "monitoring"

    @classmethod
    def _supported_actions(cls) -> tuple[str, ...]:
        return ("add_dashboard", "query", "alert_define", "sli_track")

    async def _handle_action(
        self, action: str, payload: dict[str, Any],
    ) -> dict[str, Any]:
        if action == "query":
            # Read path stub — return empty result series.
            return {
                "_stub": True,
                "provider": payload.get("provider", "prometheus"),
                "query": payload.get("query", ""),
                "series": [],
                "queried_at": utcnow_iso(),
            }
        if action == "sli_track":
            return {
                "_stub": True,
                "sli_id": payload.get("sli_id"),
                "registered_at": utcnow_iso(),
            }
        if action in ("add_dashboard", "alert_define"):
            raise NotImplementedError(
                f"monitoring.{action} — v1.1+ (Wave 3 provider plumbing)"
            )
        raise NotImplementedError(f"unsupported monitoring action {action!r}")


__all__: list[str] = ["MonitoringControlPlane"]
