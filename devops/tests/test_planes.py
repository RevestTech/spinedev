"""Per-plane contract tests (V3 #11; Wave 2 Squad 3).

Verifies that every one of the 8 control planes:

  * is importable;
  * exposes a non-empty ``supported_actions`` tuple;
  * has ``name`` matching its expected ENUM value
    (one of ``spine_devops.control_plane_name``);
  * instantiates without I/O;
  * ``invoke()`` of a known stub action returns either
    ``status='stub_implementation'`` or ``status='ok'`` and writes the
    audit/action_log envelope fields.

DB writes are skipped (``SPINE_DB_URL`` unset) — the base class returns
synthetic UUIDs in that mode so unit tests don't need Postgres.
"""

from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

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
from devops.planes.base import ActionResult, ControlPlane, PlaneStatus


# (class, expected_name, expected_actions_count)
_PLANES: list[tuple[type[ControlPlane], str, int]] = [
    (CIControlPlane, "ci_cd", 4),
    (InfrastructureControlPlane, "infrastructure", 5),
    (SecretsControlPlane, "secrets", 3),
    (MonitoringControlPlane, "monitoring", 4),
    (AlertingControlPlane, "alerting", 4),
    (DeploymentControlPlane, "deployment", 4),
    (DatabaseControlPlane, "database", 4),
    (NetworkingControlPlane, "networking", 4),
]


class PlaneShapeTests(unittest.TestCase):
    """Each plane has the right class shape per the spec."""

    @classmethod
    def setUpClass(cls) -> None:
        # Ensure no DB URL is set so writes short-circuit.
        os.environ.pop("SPINE_DB_URL", None)

    def test_eight_planes_total(self) -> None:
        self.assertEqual(len(_PLANES), 8,
            "Spec requires exactly 8 control planes (V27 ENUM).")

    def test_each_plane_has_expected_name(self) -> None:
        for cls, expected_name, _ in _PLANES:
            with self.subTest(plane=cls.__name__):
                inst = cls()
                self.assertEqual(inst.name, expected_name)

    def test_each_plane_supported_actions_non_empty(self) -> None:
        for cls, _, expected_count in _PLANES:
            with self.subTest(plane=cls.__name__):
                actions = cls.supported_actions()
                self.assertIsInstance(actions, list)
                self.assertGreater(len(actions), 0)
                self.assertEqual(len(actions), expected_count)
                # Sanity: no duplicates.
                self.assertEqual(len(set(actions)), len(actions))

    def test_each_plane_instantiates(self) -> None:
        for cls, _, _ in _PLANES:
            with self.subTest(plane=cls.__name__):
                inst = cls()
                self.assertIsInstance(inst, ControlPlane)


class PlaneSupportedActionsContentTests(unittest.TestCase):
    """Spec calls out specific action names per plane — pin them down."""

    EXPECTED: dict[str, set[str]] = {
        "ci_cd": {"trigger_build", "cancel_build", "retry_build", "status_check"},
        "infrastructure": {"plan", "apply", "destroy", "drift_detect", "cost_estimate"},
        "secrets": {"rotate", "audit_access", "list_active_leases"},
        "monitoring": {"add_dashboard", "query", "alert_define", "sli_track"},
        "alerting": {"route", "ack", "escalate", "silence"},
        "deployment": {"deploy", "rollback", "canary", "feature_flag_toggle"},
        "database": {"migrate", "backup", "restore_test", "slow_query_report"},
        "networking": {"dns_update", "lb_health", "ingress_route", "ssl_cert_renew"},
    }

    def test_action_sets_match_spec(self) -> None:
        for cls, name, _ in _PLANES:
            with self.subTest(plane=name):
                self.assertEqual(set(cls.supported_actions()),
                                 self.EXPECTED[name])


class PlaneInvokeStubTests(unittest.IsolatedAsyncioTestCase):
    """Calling a stub action returns a well-formed ActionResult."""

    async def asyncSetUp(self) -> None:
        os.environ.pop("SPINE_DB_URL", None)

    async def test_status_check_returns_stub(self) -> None:
        plane = CIControlPlane()
        result = await plane.invoke("status_check", {"run_id": "x", "project_id": None})
        self.assertIsInstance(result, ActionResult)
        self.assertEqual(result.plane_name, "ci_cd")
        self.assertEqual(result.action, "status_check")
        self.assertEqual(result.status, "stub_implementation")
        self.assertIsNone(result.error)

    async def test_unsupported_action_returns_error(self) -> None:
        plane = CIControlPlane()
        result = await plane.invoke("not_a_real_action", {})
        self.assertEqual(result.status, "error")
        self.assertIn("unsupported", (result.error or "").lower())

    async def test_high_impact_action_via_plane_raises_not_implemented(self) -> None:
        """Plane-direct call (no dispatcher gating) returns stub_implementation
        because v1.0 handlers raise NotImplementedError, which base.invoke()
        translates into a stub_implementation envelope."""
        plane = InfrastructureControlPlane()
        result = await plane.invoke("apply", {})
        self.assertEqual(result.status, "stub_implementation")

    async def test_status_call_returns_planestatus(self) -> None:
        with patch(
            "devops.planes.monitoring._probe_hub_healthz_sync",
            return_value=(True, "http://localhost:8090/healthz"),
        ):
            plane = MonitoringControlPlane()
            status = await plane.status(project_id=None)
        self.assertIsInstance(status, PlaneStatus)
        self.assertEqual(status.plane_name, "monitoring")
        self.assertEqual(status.status, "active")


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(unittest.main())  # type: ignore[arg-type]
