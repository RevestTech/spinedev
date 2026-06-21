"""
Unit tests for Temporal workflow and activity dataclasses.

Tests:
  - AuditInput / ProjectMeta / ScanResult serialization
  - FindingInput / FixAttempt / FixResult construction
  - AuditSummary construction
  - Activity function signatures exist (smoke test)
"""

from __future__ import annotations

import json
import uuid


from tron.workflows.activities import (
    AuditInput,
    AuditSummary,
    AgentResult,
    FindingInput,
    FixAttempt,
    FixResult,
    ProjectMeta,
    ScanResult,
)


class TestAuditInput:

    def test_construction(self):
        inp = AuditInput(
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            triggered_by="manual",
            scope="full",
        )
        assert inp.scope == "full"
        assert inp.triggered_by == "manual"

    def test_default_scope(self):
        inp = AuditInput(
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
        )
        assert inp.scope == "full"


class TestProjectMeta:

    def test_construction(self):
        pm = ProjectMeta(
            project_id=str(uuid.uuid4()),
            name="Test Project",
            repo_url="https://github.com/test/repo",
            default_branch="main",
        )
        assert pm.name == "Test Project"
        assert pm.default_branch == "main"

    def test_no_repo_url(self):
        pm = ProjectMeta(
            project_id=str(uuid.uuid4()),
            name="No Repo",
            repo_url=None,
            default_branch="main",
        )
        assert pm.repo_url is None


class TestScanResult:

    def test_construction(self):
        sr = ScanResult(
            file_count=10,
            total_size_kb=25.5,
            languages=["python", "javascript"],
            file_contents={"app.py": "code"},
        )
        assert sr.file_count == 10
        assert len(sr.languages) == 2
        assert "app.py" in sr.file_contents


class TestAgentResult:

    def test_construction(self):
        ar = AgentResult(
            agent_id="security-iso",
            specialization="security",
            findings_count=5,
            findings_json=json.dumps([{"type": "sql_injection"}]),
            duration_seconds=12.5,
            llm_tokens_used=500,
            llm_cost_usd=0.005,
            errors=[],
        )
        assert ar.findings_count == 5
        assert ar.errors == []

    def test_with_errors(self):
        ar = AgentResult(
            agent_id="test",
            specialization="security",
            findings_count=0,
            findings_json="[]",
            duration_seconds=1.0,
            llm_tokens_used=0,
            llm_cost_usd=0.0,
            errors=["timeout"],
        )
        assert len(ar.errors) == 1


class TestAuditSummary:

    def test_construction(self):
        s = AuditSummary(
            audit_run_id=str(uuid.uuid4()),
            findings_total=14,
            findings_critical=1,
            findings_high=3,
            findings_medium=8,
            findings_low=2,
            duration_seconds=45.0,
            agents_run=3,
        )
        assert s.findings_total == 14
        assert s.agents_run == 3

    def test_counts_sum(self):
        s = AuditSummary(
            audit_run_id="x",
            findings_total=10,
            findings_critical=2,
            findings_high=3,
            findings_medium=3,
            findings_low=2,
            duration_seconds=30.0,
            agents_run=2,
        )
        total = s.findings_critical + s.findings_high + s.findings_medium + s.findings_low
        assert total == s.findings_total


class TestFindingInput:

    def test_construction(self):
        fi = FindingInput(
            finding_id=str(uuid.uuid4()),
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            file_path="app.py",
            line_number=12,
            vulnerability_type="sql_injection",
            severity="critical",
            description="SQL injection",
            code_snippet="cursor.execute(...)",
        )
        assert fi.file_path == "app.py"
        assert fi.severity == "critical"


class TestFixAttempt:

    def test_success(self):
        fa = FixAttempt(
            iteration=1,
            fix_code="fixed_code()",
            verification_passed=True,
            verification_output="PASS",
        )
        assert fa.verification_passed is True
        assert fa.error_message is None

    def test_failure(self):
        fa = FixAttempt(
            iteration=2,
            fix_code="",
            verification_passed=False,
            verification_output="FAIL",
            error_message="LLM timeout",
        )
        assert fa.verification_passed is False
        assert fa.error_message == "LLM timeout"


class TestFixResult:

    def test_success(self):
        fr = FixResult(
            finding_id=str(uuid.uuid4()),
            success=True,
            iterations_completed=1,
            final_fix="safe_code()",
        )
        assert fr.success is True
        assert fr.error_message is None

    def test_escalated(self):
        fr = FixResult(
            finding_id=str(uuid.uuid4()),
            success=False,
            iterations_completed=3,
            error_message="Escalated after 3 attempts",
        )
        assert fr.success is False
        assert fr.iterations_completed == 3
