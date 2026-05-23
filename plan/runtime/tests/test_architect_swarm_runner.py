"""Tests for architect swarm Hub wiring."""

from __future__ import annotations

from unittest.mock import patch

from plan.runtime.architect_swarm_runner import run_architect_swarm


def test_run_architect_swarm_returns_trd_markdown() -> None:
    fake_trd = {
        "version": "trd-v1",
        "project_id": "00000000-0000-0000-0000-000000000001",
        "prd_ref": "PRD::x#prd-v1",
        "architecture": {
            "system_overview": "Overview text long enough for validation.",
            "components": [{"name": "api", "responsibility": "HTTP API"}],
            "data_flow": "Client to API to DB flow described here.",
        },
        "tech_choices": [{
            "concern": "stack",
            "decision": "Python FastAPI",
            "rationale": "Fast to ship MVP",
            "alternatives_considered": [],
        }],
        "nfrs": {
            "performance": "P95 under 500ms",
            "security": "Auth required",
            "scalability": "Horizontal scale",
            "observability": "Structured logs",
            "cost": "Low idle cost",
        },
        "scope_estimate": {"epics_count": 1, "stories_count": 3, "estimated_size": "M"},
        "cost_projection": {
            "build_phase_estimate": 100.0,
            "verify_phase_estimate": 50.0,
            "total_estimate": 150.0,
        },
        "risks": [],
        "open_questions": [],
        "metadata": {"created_by": "test", "status": "draft"},
    }
    with patch("plan.runtime.architect_swarm_runner.run_swarm") as mock_swarm:
        mock_swarm.return_value = {
            "run_id": "swarm-1",
            "contributions": [{"scout_role": "engineer"}],
            "unrun": [],
            "trd_payload": fake_trd,
            "validation_errors": [],
        }
        result = run_architect_swarm({
            "project_uuid": "00000000-0000-0000-0000-000000000001",
            "name": "Demo",
            "project_type": "feature",
            "metadata": {"description": "Todo app"},
        })
    assert result.ok is True
    assert "TRD" in result.trd_md or "trd" in result.trd_md.lower()
    assert result.swarm_run_id == "swarm-1"
