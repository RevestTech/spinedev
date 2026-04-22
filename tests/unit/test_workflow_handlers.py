"""
Unit tests for Temporal workflow handler functions.

Tests the @workflow.defn classes (AuditWorkflow, FixWorkflow) by mocking
the workflow execution context and activity calls.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tron.workflows.activities import (
    AuditInput,
    AuditSummary,
    AgentResult,
    FindingInput,
    FixAttempt,
    FixResult,
    ProjectMeta,
    ScanResult,
    VerificationResult,
    mark_audit_run_failed,
)


def _noop_layer3() -> VerificationResult:
    return VerificationResult(
        verified_count=0,
        rejected_count=0,
        unverified_count=0,
        skipped_count=0,
        confidence_adjustments=[],
    )


def _mock_workflow():
    """Patch temporalio workflow context."""
    return patch("tron.workflows.audit_workflow.workflow", MagicMock())


def _mock_workflow_fix():
    """Patch temporalio workflow context for fix_workflow."""
    return patch("tron.workflows.fix_workflow.workflow", MagicMock())


# ── AuditWorkflow ──────────────────────────────────────────────────


class TestAuditWorkflowRun:
    """Test AuditWorkflow.run method."""

    async def test_run_full_scope_all_agents(self):
        from tron.workflows.audit_workflow import AuditWorkflow

        audit_input = AuditInput(
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            scope="full",
        )

        audit_run = AuditWorkflow()

        project_meta = ProjectMeta(
            project_id=audit_input.project_id,
            name="TestProject",
            repo_url="https://github.com/test/repo",
            default_branch="main",
        )

        scan_result = ScanResult(
            file_count=5,
            total_size_kb=50.0,
            languages=["python"],
            file_contents={"app.py": "code"},
        )

        agent_results = [
            AgentResult(
                agent_id="security-iso-primary",
                specialization="security",
                findings_count=2,
                findings_json="[]",
                duration_seconds=1.0,
                llm_tokens_used=100,
                llm_cost_usd=0.01,
                errors=[],
            ),
            AgentResult(
                agent_id="builder-iso-primary",
                specialization="builder",
                findings_count=1,
                findings_json="[]",
                duration_seconds=1.0,
                llm_tokens_used=100,
                llm_cost_usd=0.01,
                errors=[],
            ),
            AgentResult(
                agent_id="performance-iso-primary",
                specialization="performance",
                findings_count=0,
                findings_json="[]",
                duration_seconds=1.0,
                llm_tokens_used=100,
                llm_cost_usd=0.01,
                errors=[],
            ),
            AgentResult(
                agent_id="qa-iso-primary",
                specialization="qa",
                findings_count=0,
                findings_json="[]",
                duration_seconds=1.0,
                llm_tokens_used=100,
                llm_cost_usd=0.01,
                errors=[],
            ),
            AgentResult(
                agent_id="compliance-iso-primary",
                specialization="compliance",
                findings_count=0,
                findings_json="[]",
                duration_seconds=1.0,
                llm_tokens_used=100,
                llm_cost_usd=0.01,
                errors=[],
            ),
            AgentResult(
                agent_id="documentation-iso-primary",
                specialization="documentation",
                findings_count=0,
                findings_json="[]",
                duration_seconds=1.0,
                llm_tokens_used=100,
                llm_cost_usd=0.01,
                errors=[],
            ),
        ]

        audit_summary = AuditSummary(
            audit_run_id=audit_input.audit_run_id,
            findings_total=3,
            findings_critical=0,
            findings_high=2,
            findings_medium=1,
            findings_low=0,
            duration_seconds=3.0,
            agents_run=6,
        )

        with _mock_workflow():
            # Mock workflow.execute_activity to return our test data
            with patch("tron.workflows.audit_workflow.workflow.execute_activity", new_callable=AsyncMock) as mock_exec:
                # Awaited: load_project_metadata, scan_repository, verify_findings_with_sandbox, synthesize_findings
                mock_exec.side_effect = [
                    project_meta,
                    scan_result,
                    _noop_layer3(),
                    audit_summary,
                ]

                with patch("tron.workflows.audit_workflow.asyncio.gather", new_callable=AsyncMock, return_value=agent_results):
                    result = await audit_run.run(audit_input)

            assert result.audit_run_id == audit_input.audit_run_id
            assert result.findings_total == 3
            assert result.agents_run == 6

    async def test_run_security_scope_only_security_agent(self):
        from tron.workflows.audit_workflow import AuditWorkflow

        audit_input = AuditInput(
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            scope="security",
        )

        audit_run = AuditWorkflow()

        project_meta = ProjectMeta(
            project_id=audit_input.project_id,
            name="TestProject",
            repo_url="https://github.com/test/repo",
            default_branch="main",
        )

        scan_result = ScanResult(
            file_count=5,
            total_size_kb=50.0,
            languages=["python"],
            file_contents={"app.py": "code"},
        )

        security_result = AgentResult(
            agent_id="security-iso-primary",
            specialization="security",
            findings_count=2,
            findings_json="[]",
            duration_seconds=1.0,
            llm_tokens_used=100,
            llm_cost_usd=0.01,
            errors=[],
        )

        audit_summary = AuditSummary(
            audit_run_id=audit_input.audit_run_id,
            findings_total=2,
            findings_critical=0,
            findings_high=2,
            findings_medium=0,
            findings_low=0,
            duration_seconds=1.0,
            agents_run=1,
        )

        with _mock_workflow():
            with patch("tron.workflows.audit_workflow.workflow.execute_activity", new_callable=AsyncMock) as mock_exec:
                # Only awaited calls consume side_effect:
                # 1. load_project_metadata, 2. scan_repository, 3. synthesize_findings
                # Agent calls create coroutines but gather is patched so they're never awaited
                mock_exec.side_effect = [
                    project_meta,
                    scan_result,
                    _noop_layer3(),
                    audit_summary,
                ]

                with patch("tron.workflows.audit_workflow.asyncio.gather", new_callable=AsyncMock, return_value=[security_result]):
                    result = await audit_run.run(audit_input)

            assert result.findings_total == 2
            assert result.agents_run == 1

    async def test_run_quality_scope_only_builder_agent(self):
        from tron.workflows.audit_workflow import AuditWorkflow

        audit_input = AuditInput(
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            scope="quality",
        )

        audit_run = AuditWorkflow()

        project_meta = ProjectMeta(
            project_id=audit_input.project_id,
            name="TestProject",
            repo_url=None,
            default_branch="main",
        )

        scan_result = ScanResult(
            file_count=1,
            total_size_kb=10.0,
            languages=["python"],
            file_contents={"app.py": "code"},
        )

        builder_result = AgentResult(
            agent_id="builder-iso-primary",
            specialization="builder",
            findings_count=1,
            findings_json="[]",
            duration_seconds=2.0,
            llm_tokens_used=200,
            llm_cost_usd=0.02,
            errors=[],
        )

        audit_summary = AuditSummary(
            audit_run_id=audit_input.audit_run_id,
            findings_total=1,
            findings_critical=0,
            findings_high=0,
            findings_medium=1,
            findings_low=0,
            duration_seconds=2.0,
            agents_run=1,
        )

        with _mock_workflow():
            with patch("tron.workflows.audit_workflow.workflow.execute_activity", new_callable=AsyncMock) as mock_exec:
                # Only awaited calls consume side_effect:
                # 1. load_project_metadata, 2. scan_repository, 3. synthesize_findings
                # Agent calls create coroutines but gather is patched so they're never awaited
                mock_exec.side_effect = [
                    project_meta,
                    scan_result,
                    _noop_layer3(),
                    audit_summary,
                ]

                with patch("tron.workflows.audit_workflow.asyncio.gather", new_callable=AsyncMock, return_value=[builder_result]):
                    result = await audit_run.run(audit_input)

            assert result.findings_total == 1
            assert result.agents_run == 1

    async def test_run_performance_scope_only_performance_agent(self):
        from tron.workflows.audit_workflow import AuditWorkflow

        audit_input = AuditInput(
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            scope="performance",
        )

        audit_run = AuditWorkflow()

        project_meta = ProjectMeta(
            project_id=audit_input.project_id,
            name="TestProject",
            repo_url=None,
            default_branch="main",
        )

        scan_result = ScanResult(
            file_count=1,
            total_size_kb=10.0,
            languages=["python"],
            file_contents={"app.py": "code"},
        )

        perf_result = AgentResult(
            agent_id="performance-iso-primary",
            specialization="performance",
            findings_count=0,
            findings_json="[]",
            duration_seconds=1.5,
            llm_tokens_used=150,
            llm_cost_usd=0.015,
            errors=[],
        )

        audit_summary = AuditSummary(
            audit_run_id=audit_input.audit_run_id,
            findings_total=0,
            findings_critical=0,
            findings_high=0,
            findings_medium=0,
            findings_low=0,
            duration_seconds=1.5,
            agents_run=1,
        )

        with _mock_workflow():
            with patch("tron.workflows.audit_workflow.workflow.execute_activity", new_callable=AsyncMock) as mock_exec:
                # Only awaited calls consume side_effect:
                # 1. load_project_metadata, 2. scan_repository, 3. synthesize_findings
                # Agent calls create coroutines but gather is patched so they're never awaited
                mock_exec.side_effect = [
                    project_meta,
                    scan_result,
                    _noop_layer3(),
                    audit_summary,
                ]

                with patch("tron.workflows.audit_workflow.asyncio.gather", new_callable=AsyncMock, return_value=[perf_result]):
                    result = await audit_run.run(audit_input)

            assert result.findings_total == 0
            assert result.agents_run == 1

    async def test_run_calls_mark_failed_then_reraises_on_phase_error(self):
        """After a phase failure, mark_audit_run_failed activity runs then the error propagates."""
        from tron.workflows.audit_workflow import AuditWorkflow

        audit_input = AuditInput(
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            scope="security",
        )
        audit_run = AuditWorkflow()

        with _mock_workflow():
            with patch(
                "tron.workflows.audit_workflow.workflow.execute_activity",
                new_callable=AsyncMock,
            ) as mock_exec:
                mock_exec.side_effect = [
                    RuntimeError("load_project_metadata failed"),
                    None,
                ]
                with pytest.raises(RuntimeError, match="load_project_metadata failed"):
                    await audit_run.run(audit_input)

                assert mock_exec.await_count >= 2
                second = mock_exec.await_args_list[1]
                assert second.args[0] is mark_audit_run_failed
                assert second.kwargs["args"][0] == audit_input.audit_run_id
                assert "load_project_metadata failed" in second.kwargs["args"][1]


# ── FixWorkflow ────────────────────────────────────────────────────


class TestFixWorkflowRun:
    """Test FixWorkflow.run method."""

    async def test_run_fix_succeeds_on_first_iteration(self):
        from tron.workflows.fix_workflow import FixWorkflow

        finding_input = FindingInput(
            finding_id=str(uuid.uuid4()),
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            file_path="app.py",
            line_number=10,
            vulnerability_type="sql_injection",
            severity="high",
            description="SQL injection via string concatenation",
            code_snippet="cursor.execute(q + user)",
        )

        fix_workflow = FixWorkflow()

        fix_attempt = FixAttempt(
            iteration=1,
            fix_code="cursor.execute('SELECT * FROM t WHERE id = ?', (user,))",
            verification_passed=False,
            verification_output="",
        )

        verified_attempt = FixAttempt(
            iteration=1,
            fix_code="cursor.execute('SELECT * FROM t WHERE id = ?', (user,))",
            verification_passed=True,
            verification_output="PASS: Fix appears to address the vulnerability",
        )

        with _mock_workflow_fix():
            with patch("tron.workflows.fix_workflow.workflow.execute_activity", new_callable=AsyncMock) as mock_exec:
                mock_exec.side_effect = [
                    fix_attempt,
                    verified_attempt,
                    finding_input.finding_id,  # persist_fix return
                ]

                result = await fix_workflow.run(finding_input)

            assert result.finding_id == finding_input.finding_id
            assert result.success is True
            assert result.iterations_completed == 1
            assert result.final_fix is not None

    async def test_run_fix_retries_and_succeeds(self):
        from tron.workflows.fix_workflow import FixWorkflow

        finding_input = FindingInput(
            finding_id=str(uuid.uuid4()),
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            file_path="app.py",
            line_number=10,
            vulnerability_type="sql_injection",
            severity="high",
            description="SQL injection",
            code_snippet="bad code",
        )

        fix_workflow = FixWorkflow()

        # Iteration 1: Generation fails
        failed_attempt = FixAttempt(
            iteration=1,
            fix_code="",
            verification_passed=False,
            verification_output="",
            error_message="LLM timeout",
        )

        # Iteration 2: Generation succeeds but verification fails
        attempt_2 = FixAttempt(
            iteration=2,
            fix_code="bad_fix_code",
            verification_passed=False,
            verification_output="",
        )

        verified_2 = FixAttempt(
            iteration=2,
            fix_code="bad_fix_code",
            verification_passed=False,
            verification_output="FAIL: Still vulnerable",
        )

        # Iteration 3: Succeeds
        attempt_3 = FixAttempt(
            iteration=3,
            fix_code="good_fix",
            verification_passed=False,
            verification_output="",
        )

        verified_3 = FixAttempt(
            iteration=3,
            fix_code="good_fix",
            verification_passed=True,
            verification_output="PASS",
        )

        with _mock_workflow_fix():
            with patch("tron.workflows.fix_workflow.workflow.execute_activity", new_callable=AsyncMock) as mock_exec:
                mock_exec.side_effect = [
                    failed_attempt,
                    attempt_2,
                    verified_2,
                    attempt_3,
                    verified_3,
                    finding_input.finding_id,
                ]

                result = await fix_workflow.run(finding_input)

            assert result.success is True
            assert result.iterations_completed == 3

    async def test_run_fix_exhausts_iterations_escalates(self):
        from tron.workflows.fix_workflow import FixWorkflow

        finding_input = FindingInput(
            finding_id=str(uuid.uuid4()),
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            file_path="app.py",
            line_number=10,
            vulnerability_type="xss",
            severity="medium",
            description="XSS vulnerability",
            code_snippet="bad code",
        )

        fix_workflow = FixWorkflow()

        # All iterations fail verification
        failed_verify = FixAttempt(
            iteration=1,
            fix_code="some_fix",
            verification_passed=False,
            verification_output="FAIL: Still vulnerable",
        )

        escalation_msg = "Escalated finding after 3 attempts"

        with _mock_workflow_fix():
            with patch("tron.workflows.fix_workflow.workflow.execute_activity", new_callable=AsyncMock) as mock_exec:
                mock_exec.side_effect = [
                    # Iteration 1
                    failed_verify,
                    failed_verify,
                    # Iteration 2
                    failed_verify,
                    failed_verify,
                    # Iteration 3
                    failed_verify,
                    failed_verify,
                    # Escalate
                    escalation_msg,
                ]

                result = await fix_workflow.run(finding_input)

            assert result.success is False
            assert result.iterations_completed == 3
            assert "Escalated" in result.error_message

    async def test_run_fix_generation_error_continues(self):
        from tron.workflows.fix_workflow import FixWorkflow

        finding_input = FindingInput(
            finding_id=str(uuid.uuid4()),
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            file_path="app.py",
            line_number=10,
            vulnerability_type="hardcoded_secrets",
            severity="high",
            description="Hardcoded secret",
            code_snippet="password = 'secret'",
        )

        fix_workflow = FixWorkflow()

        # First iteration: generation error
        gen_error = FixAttempt(
            iteration=1,
            fix_code="",
            verification_passed=False,
            verification_output="",
            error_message="LLM service unavailable",
        )

        # Second iteration: succeeds
        attempt_2 = FixAttempt(
            iteration=2,
            fix_code="good code",
            verification_passed=False,
            verification_output="",
        )

        verified_2 = FixAttempt(
            iteration=2,
            fix_code="good code",
            verification_passed=True,
            verification_output="PASS",
        )

        with _mock_workflow_fix():
            with patch("tron.workflows.fix_workflow.workflow.execute_activity", new_callable=AsyncMock) as mock_exec:
                mock_exec.side_effect = [
                    gen_error,
                    attempt_2,
                    verified_2,
                    finding_input.finding_id,
                ]

                result = await fix_workflow.run(finding_input)

            assert result.success is True
            assert result.iterations_completed == 2
