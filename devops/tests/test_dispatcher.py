"""Dispatcher contract tests (V3 #11; Wave 2 Squad 3).

Covers:

  * Registry resolves all 8 planes by ENUM name.
  * ``invoke()`` of a known stub action emits the expected envelope.
  * Cite-or-Refuse: HIGH_IMPACT actions without ``citation`` are
    refused with ``status='error'`` + refusal-audit recording hook.
  * MCP tool surface auto-registers (devops_invoke / devops_status /
    devops_planes_list).
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from devops.dispatcher import DevOpsDispatcher
from devops.planes.base import ActionResult, HIGH_IMPACT_ACTIONS


class DispatcherRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ.pop("SPINE_DB_URL", None)
        self.dispatcher = DevOpsDispatcher()

    def test_eight_planes_registered(self) -> None:
        names = sorted(self.dispatcher.registered_planes())
        self.assertEqual(len(names), 8)
        self.assertEqual(names, sorted([
            "ci_cd", "infrastructure", "secrets", "monitoring",
            "alerting", "deployment", "database", "networking",
        ]))

    def test_get_unknown_plane_raises(self) -> None:
        with self.assertRaises(KeyError):
            self.dispatcher.get("not_a_plane")

    def test_supported_actions_per_plane_via_dispatcher(self) -> None:
        actions = self.dispatcher.supported_actions("ci_cd")
        self.assertIn("status_check", actions)

    def test_requires_citation_classifier(self) -> None:
        # Per spec — apply/deploy/rotate/destroy must be high-impact.
        for act in ("apply", "deploy", "rotate", "destroy"):
            with self.subTest(action=act):
                self.assertTrue(self.dispatcher.requires_citation(act))
                self.assertIn(act, HIGH_IMPACT_ACTIONS)
        # And read-only actions must not be high-impact.
        for act in ("status_check", "plan", "drift_detect"):
            with self.subTest(action=act):
                self.assertFalse(self.dispatcher.requires_citation(act))


class DispatcherInvokeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        os.environ.pop("SPINE_DB_URL", None)
        self.dispatcher = DevOpsDispatcher()

    async def test_invoke_stub_action_returns_ok_or_stub(self) -> None:
        result = await self.dispatcher.invoke(
            "ci_cd", "status_check", {"run_id": "abc"},
        )
        self.assertIsInstance(result, ActionResult)
        self.assertEqual(result.plane_name, "ci_cd")
        self.assertEqual(result.status, "stub_implementation")
        self.assertIsNone(result.error)

    async def test_invoke_emits_audit_anchor_or_action_log_id(self) -> None:
        """Either an audit_chain_anchor or at least an action_log_id is
        always present so downstream Cite-or-Refuse middleware has
        evidence to point at."""
        result = await self.dispatcher.invoke(
            "ci_cd", "status_check", {"run_id": "abc"},
        )
        self.assertTrue(
            (result.audit_chain_anchor is not None)
            or (result.action_log_id is not None),
            "every invoke must emit at least one piece of cite-able evidence",
        )


class DispatcherCiteOrRefuseTests(unittest.IsolatedAsyncioTestCase):
    """HIGH_IMPACT actions w/o citation MUST be refused."""

    async def asyncSetUp(self) -> None:
        os.environ.pop("SPINE_DB_URL", None)
        self.dispatcher = DevOpsDispatcher()

    async def test_high_impact_without_citation_refused(self) -> None:
        # ``deploy`` is HIGH_IMPACT — no citation = refusal.
        result = await self.dispatcher.invoke(
            "deployment", "deploy", {"build_id": "x"},
        )
        self.assertEqual(result.status, "error")
        self.assertIn("Cite-or-Refuse", result.error or "")
        self.assertIn("V3 #12", result.error or "")

    async def test_high_impact_with_citation_dispatches(self) -> None:
        # With citation present, dispatcher should defer to the plane
        # (which raises NotImplementedError → stub_implementation).
        result = await self.dispatcher.invoke(
            "deployment", "deploy",
            {"build_id": "x",
             "citation": [{"type": "audit_hash", "ref": "abc"}]},
        )
        self.assertNotEqual(result.status, "error")
        self.assertEqual(result.status, "stub_implementation")

    async def test_refusal_records_audit_event(self) -> None:
        """Refusal must invoke the audit-record builder once."""
        with mock.patch.object(self.dispatcher, "_record_refusal",
                               wraps=self.dispatcher._record_refusal) as spy:
            await self.dispatcher.invoke(
                "infrastructure", "apply", {"workspace": "prod"},
            )
            self.assertEqual(spy.call_count, 1)
            kwargs = spy.call_args.kwargs
            self.assertEqual(kwargs["plane_name"], "infrastructure")
            self.assertEqual(kwargs["action"], "apply")
            self.assertEqual(kwargs["reason"], "missing_or_empty_citation")


class McpToolRegistrationTests(unittest.TestCase):
    """Importing devops.mcp_tools must register 3 tools in TOOL_REGISTRY."""

    def test_three_tools_registered(self) -> None:
        from shared.mcp.tools import TOOL_REGISTRY

        # Importing the module triggers the @register_tool decorators.
        import devops.mcp_tools  # noqa: F401

        for name in ("devops_invoke", "devops_status", "devops_planes_list"):
            with self.subTest(tool=name):
                self.assertIn(name, TOOL_REGISTRY,
                              f"tool {name!r} not registered")

    def test_devops_invoke_requires_citation(self) -> None:
        from shared.mcp.tools import TOOL_REGISTRY

        import devops.mcp_tools  # noqa: F401

        spec = TOOL_REGISTRY["devops_invoke"]
        self.assertTrue(spec.requires_citation,
            "devops_invoke must carry requires_citation=True per V3 #12")

    def test_devops_status_is_read_only(self) -> None:
        from shared.mcp.tools import TOOL_REGISTRY

        import devops.mcp_tools  # noqa: F401

        spec = TOOL_REGISTRY["devops_status"]
        self.assertFalse(spec.requires_citation)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
