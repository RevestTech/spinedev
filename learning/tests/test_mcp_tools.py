"""MCP-tool tests for shared.mcp.tools.learning.

Confirms:
  * All 4 tools register.
  * learning_grant_cross_org_consent is the only one tagged
    requires_citation=True (V3 #12).
  * Input validation refuses bad scope values.
  * contribute returns a ToolResponse with the gated tiers in .data.
"""
from __future__ import annotations

import unittest
from unittest import mock

# Importing the module registers the tools as a side-effect.
import shared.mcp.tools.learning as learning_tools
from shared.mcp.tools import TOOL_REGISTRY


class RegistrationTest(unittest.TestCase):
    def test_all_four_tools_present(self) -> None:
        for name in (
            "learning_contribute",
            "learning_query",
            "learning_grant_cross_org_consent",
            "learning_revoke_cross_org_consent",
        ):
            self.assertIn(name, TOOL_REGISTRY, f"missing {name}")

    def test_only_grant_requires_citation(self) -> None:
        self.assertTrue(
            TOOL_REGISTRY["learning_grant_cross_org_consent"].requires_citation,
        )
        self.assertFalse(
            TOOL_REGISTRY["learning_contribute"].requires_citation,
        )
        self.assertFalse(
            TOOL_REGISTRY["learning_query"].requires_citation,
        )
        self.assertFalse(
            TOOL_REGISTRY["learning_revoke_cross_org_consent"].requires_citation,
        )


class ContributeToolTest(unittest.TestCase):
    def test_invalid_scope_returns_error(self) -> None:
        payload = learning_tools.LearningContributeInput(
            project_id="p", lesson_text="x", requested_scope="bogus",
        )
        resp = learning_tools.learning_contribute(payload)
        self.assertEqual(resp.status, "error")
        assert resp.error is not None
        self.assertEqual(resp.error.code, "invalid_scope")

    def test_default_scope_routes_to_project_only(self) -> None:
        payload = learning_tools.LearningContributeInput(
            project_id="p", lesson_text="x", requested_scope="project",
        )
        # Stub the actual writer so the test never hits psql.
        with mock.patch(
            "learning.contribute._default_writer",
            side_effect=lambda payload, tier, extras: f"id-{tier.value}",
        ):
            resp = learning_tools.learning_contribute(payload)
        self.assertEqual(resp.status, "ok")
        self.assertEqual(resp.data["granted_scope"], "project")
        self.assertIn("project", resp.data["written"])
        self.assertNotIn("within_hub", resp.data["written"])


class QueryToolTest(unittest.TestCase):
    def test_query_invalid_scope(self) -> None:
        payload = learning_tools.LearningQueryInput(
            project_id="p", scope="garbage",
        )
        resp = learning_tools.learning_query(payload)
        self.assertEqual(resp.status, "error")

    def test_query_returns_empty_rows_stub(self) -> None:
        payload = learning_tools.LearningQueryInput(project_id="p")
        resp = learning_tools.learning_query(payload)
        self.assertEqual(resp.status, "ok")
        self.assertEqual(resp.data["rows"], [])


class GrantConsentToolTest(unittest.TestCase):
    def test_grant_calls_consent_writer(self) -> None:
        # Patch the real DB writer the consent module uses by default.
        from learning.scope import ScopePolicy
        captured: list[str] = []

        def fake_writer(record, extras):
            captured.append(record.hub_id or "?")
            return ScopePolicy(
                hub_id=record.hub_id, project_id=record.project_id,
                within_hub_enabled=True,
                cross_org_consent=bool(record.cross_org_consent),
                granular_consent=dict(record.granular),
            )

        payload = learning_tools.LearningGrantConsentInput(
            project_id="p", hub_id="h1",
            cross_org_consent=True,
            granular={"calibration_outcomes": True},
            rationale="enterprise SOC2",
        )
        with mock.patch(
            "learning.consent._default_writer", side_effect=fake_writer,
        ):
            resp = learning_tools.learning_grant_cross_org_consent(payload)
        self.assertEqual(resp.status, "ok")
        self.assertEqual(resp.data["hub_id"], "h1")
        self.assertTrue(resp.data["cross_org_consent"])
        self.assertEqual(captured, ["h1"])

    def test_grant_handles_writer_failure(self) -> None:
        payload = learning_tools.LearningGrantConsentInput(
            project_id="p", hub_id="h1", cross_org_consent=True,
        )
        with mock.patch(
            "learning.consent._default_writer",
            side_effect=RuntimeError("psql down"),
        ):
            resp = learning_tools.learning_grant_cross_org_consent(payload)
        self.assertEqual(resp.status, "error")
        assert resp.error is not None
        self.assertEqual(resp.error.code, "consent_write_failed")


class RevokeConsentToolTest(unittest.TestCase):
    def test_revoke_category(self) -> None:
        from learning.scope import ScopePolicy

        def fake_writer(record, extras):
            return ScopePolicy(
                hub_id=record.hub_id, project_id=record.project_id,
                within_hub_enabled=True,
                cross_org_consent=bool(record.cross_org_consent),
                granular_consent=dict(record.granular),
            )

        payload = learning_tools.LearningRevokeConsentInput(
            project_id="p", hub_id="h1", category="calibration_outcomes",
        )
        with mock.patch(
            "learning.consent._default_writer", side_effect=fake_writer,
        ):
            resp = learning_tools.learning_revoke_cross_org_consent(payload)
        self.assertEqual(resp.status, "ok")
        self.assertEqual(resp.data["operation"], "revoke_category")


if __name__ == "__main__":
    unittest.main()
