"""Cite-or-Refuse middleware contract tests — Wave 1 (V3 #12).

Covers:
  * ``requires_citation=True`` tag is detected via ToolSpec.
  * Verify-class tools (verify_audit, iso_invoke, *_iso_scan) carry the
    tag.
  * Middleware rejects ok responses with empty citation list (422
    refusal envelope with code ``cite_or_refuse_refused``).
  * Middleware accepts ok responses with a valid citation list.
  * Middleware passes through error responses unchanged.
  * Refusal is recorded as an audit event (action
    ``cite_or_refuse_refused``).
"""
from __future__ import annotations

import unittest
from typing import Any
from unittest import mock
from uuid import uuid4

from pydantic import BaseModel

from shared.mcp.cite_or_refuse import (
    REFUSAL_AUDIT_ACTION, REFUSAL_ERROR_CODE, enforce,
)
from shared.mcp.schemas import Citation, ToolError, ToolResponse
from shared.mcp.tools import TOOL_REGISTRY, discover_tools


class _StubInput(BaseModel):
    project_id: str = "p"


def _ok_with_cite() -> ToolResponse:
    return ToolResponse(
        status="ok",
        data={"summary": "verify ran"},
        audit_id=uuid4(),
        citation=[Citation(type="audit_hash", ref="abcd1234")],
    )


def _ok_no_cite() -> ToolResponse:
    return ToolResponse(
        status="ok", data={"summary": "x"}, audit_id=uuid4(), citation=[],
    )


def _err_resp(code: str = "tron_not_available") -> ToolResponse:
    return ToolResponse(
        status="error", data={}, audit_id=uuid4(),
        error=ToolError(code=code, message="x", retryable=False),
        citation=[],
    )


class ToolSpecTaggingTests(unittest.TestCase):
    def test_verify_audit_requires_citation(self) -> None:
        discover_tools("shared.mcp.tools")
        spec = TOOL_REGISTRY.get("verify_audit")
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertTrue(spec.requires_citation)

    def test_iso_invoke_requires_citation(self) -> None:
        discover_tools("shared.mcp.tools")
        spec = TOOL_REGISTRY.get("iso_invoke")
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertTrue(spec.requires_citation)

    def test_iso_convenience_tools_require_citation(self) -> None:
        discover_tools("shared.mcp.tools")
        for name in (
            "security_iso_scan", "builder_iso_scan", "qa_iso_scan",
            "performance_iso_scan", "compliance_iso_scan",
            "documentation_iso_scan",
        ):
            spec = TOOL_REGISTRY.get(name)
            self.assertIsNotNone(spec, msg=name)
            assert spec is not None
            self.assertTrue(spec.requires_citation, msg=name)

    def test_non_verify_tools_default_false(self) -> None:
        discover_tools("shared.mcp.tools")
        spec = TOOL_REGISTRY.get("project_create")
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertFalse(spec.requires_citation)


class MiddlewareEnforcementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.audit_calls: list[dict[str, Any]] = []
        self._patcher = mock.patch(
            "shared.mcp.cite_or_refuse._record_refusal_audit",
            side_effect=lambda **kw: self.audit_calls.append(kw),
        )
        self._patcher.start()

    def tearDown(self) -> None:
        self._patcher.stop()

    def test_valid_citation_passes_through(self) -> None:
        def _tool(_p: _StubInput) -> ToolResponse:
            return _ok_with_cite()

        wrapped = enforce("verify_audit", _tool)
        out = wrapped(_StubInput())
        self.assertEqual(out.status, "ok")
        self.assertTrue(out.citation)
        self.assertEqual(self.audit_calls, [])

    def test_missing_citation_is_refused(self) -> None:
        def _tool(_p: _StubInput) -> ToolResponse:
            return _ok_no_cite()

        wrapped = enforce("verify_audit", _tool)
        out = wrapped(_StubInput())
        self.assertEqual(out.status, "error")
        self.assertIsNotNone(out.error)
        assert out.error is not None
        self.assertEqual(out.error.code, REFUSAL_ERROR_CODE)
        self.assertFalse(out.error.retryable)
        self.assertEqual(len(self.audit_calls), 1)
        self.assertEqual(self.audit_calls[0]["tool_name"], "verify_audit")

    def test_error_response_pass_through_without_refusal(self) -> None:
        def _tool(_p: _StubInput) -> ToolResponse:
            return _err_resp("tron_not_available")

        wrapped = enforce("verify_audit", _tool)
        out = wrapped(_StubInput())
        self.assertEqual(out.status, "error")
        assert out.error is not None
        self.assertEqual(out.error.code, "tron_not_available")
        self.assertEqual(self.audit_calls, [])

    def test_explicit_cite_or_refuse_error_passes_through(self) -> None:
        def _tool(_p: _StubInput) -> ToolResponse:
            return _err_resp("cite_or_refuse_no_kg_evidence")

        wrapped = enforce("verify_audit", _tool)
        out = wrapped(_StubInput())
        self.assertEqual(out.status, "error")
        assert out.error is not None
        self.assertEqual(out.error.code, "cite_or_refuse_no_kg_evidence")
        self.assertEqual(self.audit_calls, [])

    def test_dict_response_is_accepted(self) -> None:
        def _tool(_p: _StubInput) -> dict[str, Any]:
            return {
                "status": "ok", "data": {}, "audit_id": str(uuid4()),
                "citation": [{"type": "kg_node", "ref": "node-123"}],
            }

        wrapped = enforce("verify_audit", _tool)
        out = wrapped(_StubInput())
        self.assertEqual(out.status, "ok")
        self.assertEqual(out.citation[0].type, "kg_node")


class RefusalAuditIntegrationTests(unittest.TestCase):
    """Confirm refusal builds a real AuditRecord with the right action."""

    def test_refusal_builds_audit_record(self) -> None:
        from shared.mcp import cite_or_refuse as cr

        captured: list[Any] = []
        from shared.audit import audit_record as ar

        original = ar.AuditRecord

        class _Spy(original):  # type: ignore[misc, valid-type]
            def __init__(self, **kw: Any) -> None:
                captured.append(kw)
                super().__init__(**kw)

        with mock.patch.object(ar, "AuditRecord", _Spy):
            cr._record_refusal_audit(
                tool_name="verify_audit", actor="test_actor",
                reason="missing_or_empty_citation",
                payload=_StubInput(project_id="42"),
                original_status="ok",
            )
        self.assertEqual(len(captured), 1)
        kw = captured[0]
        self.assertEqual(kw["action"], REFUSAL_AUDIT_ACTION)
        self.assertEqual(kw["subject_id"], "verify_audit")
        self.assertEqual(kw["metadata"]["reason"], "missing_or_empty_citation")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
