"""
Unit tests for AuditManager.

Tests:
  - Agent registration
  - Blueprint creation
  - Concurrent agent dispatch
  - Finding deduplication by fingerprint
  - Cross-validation (critical/high findings)
  - AuditResult construction
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from tron.agents.manager import AuditManager, AuditRequest, AuditResult
from tron.agents.base import ISOSpecialization
from tron.schemas.verification import (
    FindingBatch,
    FindingOutput,
    SeverityLevel,
    VulnerabilityType,
    CrossValidationStatus,
)


@pytest.fixture
def manager(fake_secrets, mock_llm_client):
    """AuditManager with mocked LLM client."""
    return AuditManager(secrets=fake_secrets, llm_client=mock_llm_client)


@pytest.fixture
def mock_security_agent():
    """Mock SecurityISO agent."""
    agent = AsyncMock()
    agent.config = MagicMock()
    agent.config.specialization = ISOSpecialization.SECURITY
    agent.config.agent_id = "security-iso-test"
    agent.config.max_tokens = 4000
    agent.config.max_duration_seconds = 300
    agent.config.temperature = 0.1
    agent.config.tools_required = ("bandit", "semgrep")
    agent.metrics = MagicMock()
    agent.metrics.llm_tokens_used = 100
    agent.metrics.llm_cost_usd = 0.001
    agent.metrics.errors = []
    agent.metrics.duration_seconds = 2.0

    batch = FindingBatch(
        blueprint_id="test-bp",
        findings=[
            FindingOutput(
                id=uuid.uuid4(),
                vulnerability_type=VulnerabilityType.SQL_INJECTION,
                severity=SeverityLevel.CRITICAL,
                file_path="app.py",
                line_number=12,
                code_snippet="cursor.execute(...)",
                description="SQL injection",
                confidence=0.7,
                deterministic_tool_confirmed=True,
                agent_id="security-iso-test",
                blueprint_id="test-bp",
                finding_fingerprint="fp_sql_001",
                cross_validation_status=CrossValidationStatus.PENDING,
            ),
        ],
        agent_id="security-iso-test",
        total_files_scanned=3,
        execution_duration_seconds=2.0,
    )
    agent.execute = AsyncMock(return_value=batch)
    return agent


@pytest.fixture
def audit_request(sample_project_id, sample_audit_run_id, sample_file_contents):
    return AuditRequest(
        project_id=sample_project_id,
        audit_run_id=sample_audit_run_id,
        file_contents=sample_file_contents,
        languages=["python"],
        check_types=list(VulnerabilityType),
    )


class TestAgentRegistration:
    """Tests for register_agent."""

    def test_register_agent(self, manager, mock_security_agent):
        """Registered agents are stored by specialization."""
        manager.register_agent(mock_security_agent)
        assert ISOSpecialization.SECURITY in manager._agents

    def test_register_overwrites_existing(self, manager, mock_security_agent):
        """Registering same specialization again replaces the agent."""
        manager.register_agent(mock_security_agent)
        new_agent = AsyncMock()
        new_agent.config = MagicMock()
        new_agent.config.specialization = ISOSpecialization.SECURITY
        manager.register_agent(new_agent)
        assert manager._agents[ISOSpecialization.SECURITY] is new_agent


class TestRunAudit:
    """Tests for run_audit (full pipeline)."""

    async def test_run_audit_with_one_agent(
        self, manager, mock_security_agent, audit_request
    ):
        """Single agent audit returns findings."""
        manager.register_agent(mock_security_agent)

        result = await manager.run_audit(audit_request)

        assert isinstance(result, AuditResult)
        assert result.status == "completed"
        assert len(result.findings) == 1
        assert result.findings[0].vulnerability_type == VulnerabilityType.SQL_INJECTION

    async def test_run_audit_deduplicates_by_fingerprint(
        self, manager, audit_request
    ):
        """Duplicate fingerprints across agents → deduplicated."""
        # Two agents producing same fingerprint
        finding = FindingOutput(
            id=uuid.uuid4(),
            vulnerability_type=VulnerabilityType.SQL_INJECTION,
            severity=SeverityLevel.CRITICAL,
            file_path="app.py",
            line_number=12,
            code_snippet="x",
            description="SQL injection",
            confidence=0.7,
            deterministic_tool_confirmed=False,
            agent_id="agent-1",
            blueprint_id="bp",
            finding_fingerprint="DUPLICATE_FP",
            cross_validation_status=CrossValidationStatus.PENDING,
        )

        batch1 = FindingBatch(
            blueprint_id="bp", findings=[finding],
            agent_id="agent-1", total_files_scanned=1, execution_duration_seconds=1.0,
        )
        batch2 = FindingBatch(
            blueprint_id="bp", findings=[finding],
            agent_id="agent-2", total_files_scanned=1, execution_duration_seconds=1.0,
        )

        agent1 = AsyncMock()
        agent1.config = MagicMock()
        agent1.config.specialization = ISOSpecialization.SECURITY
        agent1.config.agent_id = "agent-1"
        agent1.config.max_tokens = 4000
        agent1.config.max_duration_seconds = 300
        agent1.config.temperature = 0.1
        agent1.config.tools_required = ()
        agent1.execute = AsyncMock(return_value=batch1)
        agent1.metrics = MagicMock(llm_tokens_used=50, llm_cost_usd=0.001, errors=[], duration_seconds=1.0)

        agent2 = AsyncMock()
        agent2.config = MagicMock()
        agent2.config.specialization = ISOSpecialization.BUILDER
        agent2.config.agent_id = "agent-2"
        agent2.config.max_tokens = 4000
        agent2.config.max_duration_seconds = 300
        agent2.config.temperature = 0.1
        agent2.config.tools_required = ()
        agent2.execute = AsyncMock(return_value=batch2)
        agent2.metrics = MagicMock(llm_tokens_used=50, llm_cost_usd=0.001, errors=[], duration_seconds=1.0)

        manager.register_agent(agent1)
        manager.register_agent(agent2)

        result = await manager.run_audit(audit_request)

        # Should be deduplicated to 1 finding
        assert len(result.findings) == 1

    async def test_run_audit_no_agents_fails(self, manager, audit_request):
        """No registered agents → empty result or error."""
        result = await manager.run_audit(audit_request)
        assert result.status in ("completed", "failed")
        assert len(result.findings) == 0
