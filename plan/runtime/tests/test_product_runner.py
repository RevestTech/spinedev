"""Tests for charter-grounded product PRD generation."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

from plan.runtime.product_runner import (
    ProductResult,
    _CANONICAL_SECTIONS,
    _format_intake_context,
    intake_answers_from_transcript,
    run_product,
)


def _sample_project() -> dict:
    return {
        "id": 42,
        "project_uuid": "00000000-0000-0000-0000-00000000abcd",
        "name": "Todo CLI",
        "project_type": "feature",
        "metadata": {},
    }


def _sample_prd_md() -> str:
    return "\n".join([
        "# PRD — Todo CLI",
        "",
        "## Problem statement",
        "Developers need a fast CLI to track todos.",
        "",
        "## Users / stakeholders",
        "- **Developers**: need low-friction task capture",
        "",
        "## In scope",
        "- Add tasks",
        "- List tasks",
        "",
        "## Out of scope",
        "- Mobile app",
        "",
        "## Goals",
        "### MUST",
        "- G-M-1: Users can add a task in one command",
        "",
        "## Acceptance criteria",
        "- AC-MUST-1: MUST item delivered: add a task in one command",
        "",
        "## Open questions",
        "- OQ-1: Which shell platforms must ship day one?",
    ])


def test_format_intake_context_renders_template_answers() -> None:
    ctx = _format_intake_context({
        "primary_job": "track todos",
        "audience": "developers",
    })
    assert "primary_job" in ctx
    assert "track todos" in ctx


def test_intake_answers_from_transcript_shapes_chat_source() -> None:
    answers = intake_answers_from_transcript([
        {"role": "user", "content": "We need a todo app"},
        {"role": "assistant", "content": "Who is the primary user?"},
    ])
    assert answers["source"] == "intake_chat"
    assert "todo app" in answers["transcript_text"]
    assert len(answers["transcript"]) == 2


def test_run_product_produces_prd_with_canonical_sections() -> None:
    project = _sample_project()
    intake_answers = {
        "primary_job": "track todos from the terminal",
        "audience": "solo developers",
        "must_should_could": "MUST: add tasks quickly. SHOULD: sync later.",
    }
    fake_prd = _sample_prd_md()

    llm_resp = MagicMock()
    llm_resp.content = fake_prd

    async def _noop_async(*_a, **_k):
        return llm_resp

    with patch("plan.runtime.product_runner.call_async", side_effect=_noop_async), patch(
        "plan.runtime.product_runner._persist_metadata"
    ), patch("plan.runtime.product_runner._write_audit", return_value=True):
        result = run_product(project, intake_answers, actor="test-product")

    assert isinstance(result, ProductResult)
    assert result.ok is True
    assert result.artifact_key == "prd_md"
    assert result.prd_md == fake_prd
    for section in _CANONICAL_SECTIONS:
        assert section in result.prd_md, f"missing section: {section!r}"


def test_run_product_system_prompt_includes_charter_and_intake() -> None:
    project = _sample_project()
    intake_answers = intake_answers_from_transcript([
        {"role": "user", "content": "Build a CLI todo tracker"},
    ])
    captured: dict[str, object] = {}

    async def _capture_async(req):
        captured["system"] = req.system
        resp = MagicMock()
        resp.content = _sample_prd_md()
        return resp

    with patch("plan.runtime.product_runner.call_async", side_effect=_capture_async), patch(
        "plan.runtime.product_runner._persist_metadata"
    ), patch("plan.runtime.product_runner._write_audit", return_value=True):
        run_product(project, intake_answers)

    system = str(captured.get("system", ""))
    assert "discoverer" in system.lower()
    assert "Charter" in system or "charter" in system
    assert "Build a CLI todo tracker" in system
    assert "Problem statement" in system


def test_run_product_creates_product_directive_row() -> None:
    from pathlib import Path

    project = _sample_project()
    uid = project["project_uuid"]
    intake_answers = {"primary_job": "track todos", "audience": "devs"}

    llm_resp = MagicMock()
    llm_resp.content = _sample_prd_md()

    async def _noop_async(*_a, **_k):
        return llm_resp

    with patch("plan.runtime.product_runner.call_async", side_effect=_noop_async), patch(
        "plan.runtime.product_runner._persist_metadata"
    ), patch("plan.runtime.product_runner._write_audit", return_value=True):
        result = run_product(project, intake_answers, directive="PRODUCE_PRD_HTTP")

    repo_root = Path(__file__).resolve().parents[3]
    ws = repo_root / ".spine" / "work" / uid / "directives" / result.directive_id
    assert ws.is_dir(), f"expected directive workspace at {ws}"
    status = json.loads((ws / "status.json").read_text(encoding="utf-8"))
    assert status["role"] == "product"
    assert status["directive"] == "PRODUCE_PRD_HTTP"
    assert status["status"] == "done"
    assert (ws / "report.md").read_text(encoding="utf-8").startswith("# PRD")


def test_run_product_surfaces_llm_failure() -> None:
    project = _sample_project()

    async def _boom(*_a, **_k):
        raise RuntimeError("LLM unavailable")

    with patch("plan.runtime.product_runner.call_async", side_effect=_boom), patch(
        "plan.runtime.product_runner._write_audit", return_value=True
    ):
        result = run_product(project, {"primary_job": "x"})

    assert result.ok is False
    assert result.error_class == "RuntimeError"
    assert "LLM unavailable" in (result.error_message or "")
