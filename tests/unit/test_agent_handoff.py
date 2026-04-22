"""Unit tests for automatic agent handoff helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from tron.domain.models import AuditRun, Project
from tron.services.agent_handoff import audit_run_to_dict, normalize_finding_dict


def test_normalize_finding_dict_agent_shape() -> None:
    f = {
        "severity": "high",
        "file_path": "Dockerfile",
        "line_number": 3,
        "vulnerability_type": "security_misconfiguration",
    }
    n = normalize_finding_dict(f)
    assert n["line_start"] == 3
    assert n["severity"] == "high"
    assert "Dockerfile" in n["title"]


def test_audit_run_to_dict() -> None:
    aid = uuid4()
    pid = uuid4()
    a = AuditRun(
        id=aid,
        project_id=pid,
        workflow_id="w",
        workflow_run_id="r",
        status="completed",
        progress=100,
        findings_total=5,
        findings_critical=0,
        findings_high=2,
        findings_medium=3,
        findings_low=0,
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        completed_at=datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc),
    )
    d = audit_run_to_dict(a)
    assert d["status"] == "completed"
    assert d["findings_total"] == 5
    assert "2026-01-01" in d["started_at"]


def test_project_model_has_handoff_column() -> None:
    p = Project(name="x", agent_handoff_path="/tmp/x")
    assert p.agent_handoff_path == "/tmp/x"
