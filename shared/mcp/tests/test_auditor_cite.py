"""Cite-or-Refuse contract tests for the auditor tool (V3 #12 / Wave 2).

Confirms:
  * ``verify_build_artifact`` is registered with ``requires_citation=True``.
  * The Cite-or-Refuse middleware rejects an ok-shaped response that
    arrives with an empty ``citation`` list (422 refusal envelope).
  * The middleware accepts an ok-shaped response that carries >= 1
    citation (kg_node or audit_hash both qualify).
  * Live invocation of ``verify_build_artifact`` populates >= 1
    citation in its response envelope (audit_hash fallback minimum).
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from unittest import mock
from uuid import uuid4

from shared.mcp.cite_or_refuse import REFUSAL_ERROR_CODE, enforce
from shared.mcp.schemas import Citation, ToolError, ToolResponse
from shared.mcp.tools import TOOL_REGISTRY, discover_tools
from shared.mcp.tools.auditor import (
    VerifyBuildArtifactInput, verify_build_artifact,
)
from shared.schemas.build.build_artifact import (
    BuildArtifact, BuildCost, BuildRuntime, CodeChange, KGImpactNode,
)
from plan.artifacts._base import ArtifactMetadata


def _artifact(*, with_changes: bool = True, sealed: bool = True) -> BuildArtifact:
    """Build a minimal-but-valid sealed engineer artifact for tests."""
    started = datetime.now(timezone.utc) - timedelta(seconds=10)
    completed = started + timedelta(seconds=10)
    code_changes = (
        [CodeChange(path="src/a.py", change_type="modify",
                    diff_hash="d" * 64, lines_added=2, lines_removed=1,
                    language="python")]
        if with_changes else []
    )
    kg_impact = (
        [KGImpactNode(node_id="kg:func:src/a.py:foo",
                      node_type="Function", impact_distance=0)]
        if with_changes else []
    )
    return BuildArtifact(
        directive_id="DIR-test-1", project_id="proj-1", phase="build_in_progress",
        role="engineer", pipeline_version="pipe-v1",
        code_changes=code_changes, kg_impact=kg_impact,
        cost=BuildCost(tokens_input=10, tokens_output=5, model="claude-sonnet-4",
                       cost_usd=Decimal("0.01"), tier="low"),
        runtime=BuildRuntime(started_at=started, completed_at=completed,
                             duration_seconds=10),
        rationale="Unit test fixture: simple modify path with one KG node.",
        status="sealed" if sealed else "draft",
        metadata=ArtifactMetadata(created_by="engineer"),
    )


class ToolSpecTaggingTests(unittest.TestCase):
    """Static contract: the registry must mark the auditor tool strict-tier."""

    def test_verify_build_artifact_requires_citation(self) -> None:
        discover_tools("shared.mcp.tools")
        spec = TOOL_REGISTRY.get("verify_build_artifact")
        self.assertIsNotNone(spec, "verify_build_artifact missing from registry")
        assert spec is not None
        self.assertTrue(
            spec.requires_citation,
            "verify_build_artifact must carry requires_citation=True (V3 #12)",
        )


class MiddlewareContractTests(unittest.TestCase):
    """Behavioural contract: middleware refuses empty citation; accepts >=1."""

    def setUp(self) -> None:
        # Mute the audit-write side effect during middleware tests.
        self._patch = mock.patch(
            "shared.mcp.cite_or_refuse._record_refusal_audit",
            side_effect=lambda **_kw: None,
        )
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()

    def test_empty_citation_is_refused(self) -> None:
        def _no_cite(_p: Any) -> ToolResponse:
            return ToolResponse(status="ok", data={"v": "approved"},
                                audit_id=uuid4(), citation=[])

        wrapped = enforce("verify_build_artifact", _no_cite)
        out = wrapped(VerifyBuildArtifactInput(
            build_artifact=_artifact(), repo="r", project_id="p"))
        self.assertEqual(out.status, "error")
        assert out.error is not None
        self.assertEqual(out.error.code, REFUSAL_ERROR_CODE)
        self.assertFalse(out.error.retryable)

    def test_single_citation_passes(self) -> None:
        def _with_cite(_p: Any) -> ToolResponse:
            return ToolResponse(
                status="ok", data={"v": "approved"}, audit_id=uuid4(),
                citation=[Citation(type="kg_node", ref="kg:n:1")],
            )

        wrapped = enforce("verify_build_artifact", _with_cite)
        out = wrapped(VerifyBuildArtifactInput(
            build_artifact=_artifact(), repo="r", project_id="p"))
        self.assertEqual(out.status, "ok")
        self.assertEqual(len(out.citation), 1)
        self.assertEqual(out.citation[0].type, "kg_node")

    def test_audit_hash_citation_passes(self) -> None:
        """audit_hash is the citation-of-last-resort the auditor always emits."""
        def _with_audit(_p: Any) -> ToolResponse:
            return ToolResponse(
                status="ok", data={"v": "approved"}, audit_id=uuid4(),
                citation=[Citation(type="audit_hash", ref="deadbeef")],
            )

        wrapped = enforce("verify_build_artifact", _with_audit)
        out = wrapped(VerifyBuildArtifactInput(
            build_artifact=_artifact(), repo="r", project_id="p"))
        self.assertEqual(out.status, "ok")


class LiveCitationPopulationTests(unittest.TestCase):
    """Run the real tool: confirm it populates >= 1 citation per response."""

    def test_response_carries_at_least_one_citation(self) -> None:
        # Patch out the actual impact_radius call so we don't need a live KG.
        # Return one node so the verdict matches (approved) and we exercise
        # the kg_node citation path on top of the audit_hash fallback.
        artifact = _artifact()
        from shared.mcp.schemas import ToolResponse as _TR

        fake_impact = _TR(
            status="ok",
            data={"impacted": [
                {"node_id": "kg:func:src/a.py:foo", "node_type": "Function"},
            ]},
            audit_id=uuid4(),
        )
        with mock.patch(
            "shared.mcp.tools.kg.impact_radius", return_value=fake_impact,
        ):
            resp = verify_build_artifact(VerifyBuildArtifactInput(
                build_artifact=artifact, repo="repo", project_id="proj-1"))

        self.assertEqual(resp.status, "ok")
        self.assertGreaterEqual(
            len(resp.citation), 1,
            "verify_build_artifact must emit >= 1 citation (V3 #12)",
        )
        # Must include the audit_hash fallback citation tied to audit_id.
        audit_refs = {c.ref for c in resp.citation if c.type == "audit_hash"}
        self.assertIn(str(resp.audit_id), audit_refs)
        # Should also surface the declared kg_node as evidence.
        kg_refs = {c.ref for c in resp.citation if c.type == "kg_node"}
        self.assertIn("kg:func:src/a.py:foo", kg_refs)

    def test_kg_impact_mismatch_still_emits_citations(self) -> None:
        """A non-approved verdict must still cite — auditor diff IS the evidence."""
        artifact = _artifact()
        from shared.mcp.schemas import ToolResponse as _TR

        # Auditor discovers a node the engineer did not declare → mismatch.
        fake_impact = _TR(
            status="ok",
            data={"impacted": [
                {"node_id": "kg:func:src/a.py:foo", "node_type": "Function"},
                {"node_id": "kg:func:src/b.py:bar", "node_type": "Function"},
            ]},
            audit_id=uuid4(),
        )
        with mock.patch(
            "shared.mcp.tools.kg.impact_radius", return_value=fake_impact,
        ):
            resp = verify_build_artifact(VerifyBuildArtifactInput(
                build_artifact=artifact, repo="repo", project_id="proj-1"))

        self.assertEqual(resp.status, "ok")
        # data.verdict is set by the tool — confirm mismatch landed.
        self.assertEqual(resp.data.get("verdict"), "kg_impact_mismatch")
        # Auditor-discovered node must show up as a citation alongside
        # the declared one + the audit_hash fallback.
        refs = {(c.type, c.ref) for c in resp.citation}
        self.assertIn(("kg_node", "kg:func:src/b.py:bar"), refs)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
