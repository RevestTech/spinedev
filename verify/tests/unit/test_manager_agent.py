"""
Unit tests for AuditManager agent orchestration.

Covers:
  - Exception handling during agent runs (catching and recording errors)
  - Finding deduplication by fingerprint (keeping higher confidence/confirmed)
  - Cross-validation prompt building for different providers
  - Consensus determination from validator responses
  - Agent registration and dispatch
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


from tron.agents.base import (
    ISOConfig,
    ISOSpecialization,
    LLMProvider,
)
from tron.agents.manager import (
    AuditManager,
    AuditRequest,
    AuditResult,
)
from tron.schemas.verification import (
    Blueprint,
    BlueprintScope,
    FindingOutput,
    FindingBatch,
    CrossValidationResult,
    CrossValidationStatus,
    ConsensusLevel,
    VulnerabilityType,
    SeverityLevel,
)


class TestAuditManagerExceptionHandling:
    """Tests for exception handling during agent execution."""

    async def test_agent_run_exception_recorded(self, fake_secrets, mock_llm_client):
        """Agent exceptions should be caught and recorded."""
        manager = AuditManager(fake_secrets, llm_client=mock_llm_client)

        # Create a mock agent that raises
        failing_agent = MagicMock()
        failing_agent.config = ISOConfig(
            specialization=ISOSpecialization.SECURITY,
            agent_id="failing-agent",
            model_provider=LLMProvider.ANTHROPIC,
            model_name="claude",
        )
        failing_agent.execute = AsyncMock(side_effect=RuntimeError("Agent failed"))

        manager.register_agent(failing_agent)

        request = AuditRequest(
            project_id=uuid4(),
            audit_run_id=uuid4(),
            file_contents={"app.py": "print('hello')"},
            languages=["python"],
        )

        result = await manager.run_audit(request)

        # Result should not crash; batches should exclude the failed agent
        assert result is not None
        assert isinstance(result, AuditResult)

    async def test_no_agents_registered_returns_error(self, fake_secrets, mock_llm_client):
        """Audit with no registered agents should return error status."""
        manager = AuditManager(fake_secrets, llm_client=mock_llm_client)
        # Don't register any agents

        request = AuditRequest(
            project_id=uuid4(),
            audit_run_id=uuid4(),
            file_contents={"app.py": "x = 1"},
            languages=["python"],
        )

        result = await manager.run_audit(request)

        assert result.status == "failed"
        assert "No agents registered" in result.errors


class TestFindingDeduplication:
    """Tests for finding deduplication in merge phase."""

    def test_merge_findings_dedup_by_fingerprint(self):
        """merge_findings should deduplicate by finding_fingerprint."""
        manager = AuditManager(
            {"llm/anthropic-key": "key", "llm/openai-key": "key"}
        )

        finding1 = FindingOutput(
            vulnerability_type=VulnerabilityType.SQL_INJECTION,
            severity=SeverityLevel.CRITICAL,
            file_path="app.py",
            line_number=10,
            code_snippet="SELECT * FROM users WHERE id = ' + query + '",
            description="SQL injection",
            confidence=0.7,
            agent_id="security-agent",
            blueprint_id="bp-1",
            finding_fingerprint="fp-sql-001",
        )

        finding2 = FindingOutput(
            vulnerability_type=VulnerabilityType.SQL_INJECTION,
            severity=SeverityLevel.CRITICAL,
            file_path="app.py",
            line_number=10,
            code_snippet="SELECT * FROM users WHERE id = ' + query + '",
            description="SQL injection (from builder)",
            confidence=0.65,
            agent_id="builder-agent",
            blueprint_id="bp-2",
            finding_fingerprint="fp-sql-001",  # Same fingerprint
        )

        batch1 = FindingBatch(
            blueprint_id="bp-1",
            findings=[finding1],
            agent_id="security-agent",
            total_files_scanned=1,
            execution_duration_seconds=1.0,
        )

        batch2 = FindingBatch(
            blueprint_id="bp-2",
            findings=[finding2],
            agent_id="builder-agent",
            total_files_scanned=1,
            execution_duration_seconds=1.0,
        )

        merged = manager._merge_findings([batch1, batch2])

        # Should deduplicate to 1 finding
        assert len(merged) == 1
        # Should keep higher confidence
        assert merged[0].confidence == 0.7

    def test_merge_findings_prefers_tool_confirmed(self):
        """merge_findings should prefer tool-confirmed findings."""
        manager = AuditManager(
            {"llm/anthropic-key": "key", "llm/openai-key": "key"}
        )

        # LLM-only, high confidence
        finding_llm = FindingOutput(
            vulnerability_type=VulnerabilityType.HARDCODED_SECRETS,
            severity=SeverityLevel.HIGH,
            file_path="config.py",
            line_number=5,
            code_snippet='API_KEY = "xyz"',
            description="Secret",
            confidence=0.7,
            deterministic_tool_confirmed=False,
            agent_id="agent-1",
            blueprint_id="bp-1",
            finding_fingerprint="fp-secret-001",
        )

        # Tool-confirmed, lower confidence
        finding_tool = FindingOutput(
            vulnerability_type=VulnerabilityType.HARDCODED_SECRETS,
            severity=SeverityLevel.HIGH,
            file_path="config.py",
            line_number=5,
            code_snippet='API_KEY = "xyz"',
            description="Secret (bandit)",
            confidence=0.5,
            deterministic_tool_confirmed=True,
            agent_id="agent-2",
            blueprint_id="bp-2",
            finding_fingerprint="fp-secret-001",
        )

        batch1 = FindingBatch(
            blueprint_id="bp-1",
            findings=[finding_llm],
            agent_id="agent-1",
            total_files_scanned=1,
            execution_duration_seconds=1.0,
        )

        batch2 = FindingBatch(
            blueprint_id="bp-2",
            findings=[finding_tool],
            agent_id="agent-2",
            total_files_scanned=1,
            execution_duration_seconds=1.0,
        )

        merged = manager._merge_findings([batch1, batch2])

        assert len(merged) == 1
        # Should prefer tool-confirmed
        assert merged[0].deterministic_tool_confirmed is True


class TestCrossValidationPromptBuilding:
    """Tests for cross-validation prompt construction."""

    async def test_validate_single_finding_json_response(self, fake_secrets):
        """Cross-validation should parse JSON response correctly."""
        manager = AuditManager(fake_secrets)

        # Mock LLM response
        validator_response = MagicMock()
        validator_response.content = json.dumps({
            "found": True,
            "confidence": 0.92,
            "reasoning": "Confirmed pattern",
        })

        finding = FindingOutput(
            vulnerability_type=VulnerabilityType.XSS,
            severity=SeverityLevel.HIGH,
            file_path="template.html",
            line_number=10,
            code_snippet="{{ unsafe_var }}",
            description="XSS vulnerability",
            confidence=0.7,
            agent_id="security-agent",
            blueprint_id="bp-1",
            finding_fingerprint="fp-xss-001",
        )

        request = AuditRequest(
            project_id=uuid4(),
            audit_run_id=uuid4(),
            file_contents={"template.html": "<h1>{{ unsafe_var }}</h1>"},
            languages=["python"],
        )

        # Register a mock security agent
        mock_agent = MagicMock()
        mock_agent.config = ISOConfig(
            specialization=ISOSpecialization.SECURITY,
            agent_id="security-agent",
            model_provider=LLMProvider.ANTHROPIC,
            model_name="claude",
        )
        manager.register_agent(mock_agent)

        # Mock LLM client
        with patch.object(manager._llm, "complete", new_callable=AsyncMock,
                         return_value=validator_response):
            result = await manager._validate_single_finding(finding, request)

        assert result is not None
        assert result.finding_id == finding.id
        assert result.validator_found is True
        assert result.consensus == ConsensusLevel.CONFIRMED

    async def test_validate_single_finding_not_found(self, fake_secrets):
        """Validator response indicating finding not found."""
        manager = AuditManager(fake_secrets)

        validator_response = MagicMock()
        validator_response.content = json.dumps({
            "found": False,
            "confidence": 0.1,
            "reasoning": "Pattern not present",
        })

        finding = FindingOutput(
            vulnerability_type=VulnerabilityType.SSRF,
            severity=SeverityLevel.HIGH,
            file_path="http_client.py",
            line_number=15,
            code_snippet="requests.get(user_url)",
            description="SSRF",
            confidence=0.7,
            agent_id="security-agent",
            blueprint_id="bp-1",
            finding_fingerprint="fp-ssrf-001",
        )

        request = AuditRequest(
            project_id=uuid4(),
            audit_run_id=uuid4(),
            file_contents={"http_client.py": "import requests\nrequests.get(url)"},
            languages=["python"],
        )

        mock_agent = MagicMock()
        mock_agent.config = ISOConfig(
            specialization=ISOSpecialization.SECURITY,
            agent_id="security-agent",
            model_provider=LLMProvider.OPENAI,
            model_name="gpt-4o",
        )
        manager.register_agent(mock_agent)

        with patch.object(manager._llm, "complete", new_callable=AsyncMock,
                         return_value=validator_response):
            result = await manager._validate_single_finding(finding, request)

        assert result is not None
        assert result.validator_found is False
        assert result.consensus == ConsensusLevel.DISPUTED
        assert result.confidence_adjustment == -0.2

    async def test_validate_single_finding_no_source_code(self, fake_secrets):
        """Validation skipped when source code unavailable."""
        manager = AuditManager(fake_secrets)

        finding = FindingOutput(
            vulnerability_type=VulnerabilityType.COMMAND_INJECTION,
            severity=SeverityLevel.CRITICAL,
            file_path="missing.py",
            line_number=5,
            code_snippet="os.system(cmd)",
            description="Command injection",
            confidence=0.7,
            agent_id="security-agent",
            blueprint_id="bp-1",
            finding_fingerprint="fp-cmd-001",
        )

        request = AuditRequest(
            project_id=uuid4(),
            audit_run_id=uuid4(),
            file_contents={"other.py": "x = 1"},  # missing.py not in contents
            languages=["python"],
        )

        mock_agent = MagicMock()
        mock_agent.config = ISOConfig(
            specialization=ISOSpecialization.SECURITY,
            agent_id="security-agent",
            model_provider=LLMProvider.ANTHROPIC,
            model_name="claude",
        )
        manager.register_agent(mock_agent)

        result = await manager._validate_single_finding(finding, request)

        assert result is None


class TestConsensusApplication:
    """Tests for applying cross-validation consensus to findings."""

    def test_apply_cross_validation_confirmed_increases_status(self):
        """Confirmed validation should update status to CONFIRMED."""
        manager = AuditManager(
            {"llm/anthropic-key": "key", "llm/openai-key": "key"}
        )

        finding = FindingOutput(
            vulnerability_type=VulnerabilityType.INSECURE_DESERIALIZATION,
            severity=SeverityLevel.HIGH,
            file_path="pickle.py",
            line_number=20,
            code_snippet="pickle.loads(data)",
            description="Deserialization",
            confidence=0.6,
            cross_validation_status=CrossValidationStatus.PENDING,
            calibrated_confidence=None,
            agent_id="security-agent",
            blueprint_id="bp-1",
            finding_fingerprint="fp-pickle-001",
        )

        validation = CrossValidationResult(
            finding_id=finding.id,
            primary_agent="security-agent",
            primary_model_provider="anthropic",
            validation_agent="validator-openai",
            validator_model_provider="openai",
            primary_found=True,
            validator_found=True,
            consensus=ConsensusLevel.CONFIRMED,
            confidence_adjustment=0.15,
        )

        updated = manager._apply_cross_validation(
            [finding],
            [validation],
        )

        assert len(updated) == 1
        assert updated[0].cross_validation_status == CrossValidationStatus.CONFIRMED
        assert updated[0].calibrated_confidence == 0.75  # 0.6 + 0.15

    def test_apply_cross_validation_disputed_reduces_confidence(self):
        """Disputed validation should reduce confidence."""
        manager = AuditManager(
            {"llm/anthropic-key": "key", "llm/openai-key": "key"}
        )

        finding = FindingOutput(
            vulnerability_type=VulnerabilityType.BROKEN_AUTH,
            severity=SeverityLevel.HIGH,
            file_path="auth.py",
            line_number=10,
            code_snippet="if user:",
            description="Auth flaw",
            confidence=0.7,
            cross_validation_status=CrossValidationStatus.PENDING,
            agent_id="security-agent",
            blueprint_id="bp-1",
            finding_fingerprint="fp-auth-001",
        )

        validation = CrossValidationResult(
            finding_id=finding.id,
            primary_agent="security-agent",
            primary_model_provider="openai",
            validation_agent="validator-anthropic",
            validator_model_provider="anthropic",
            primary_found=True,
            validator_found=False,
            consensus=ConsensusLevel.DISPUTED,
            confidence_adjustment=-0.2,
        )

        updated = manager._apply_cross_validation(
            [finding],
            [validation],
        )

        assert len(updated) == 1
        assert updated[0].cross_validation_status == CrossValidationStatus.DISPUTED
        assert abs(updated[0].calibrated_confidence - 0.5) < 1e-9  # 0.7 - 0.2

    def test_apply_cross_validation_clamps_confidence_bounds(self):
        """Calibrated confidence should stay within [0.0, 1.0]."""
        manager = AuditManager(
            {"llm/anthropic-key": "key", "llm/openai-key": "key"}
        )

        # Very high confidence
        finding = FindingOutput(
            vulnerability_type=VulnerabilityType.OTHER,
            severity=SeverityLevel.MEDIUM,
            file_path="test.py",
            line_number=1,
            code_snippet="x = 1",
            description="Test",
            confidence=0.7,
            agent_id="agent",
            blueprint_id="bp-1",
            finding_fingerprint="fp-test-001",
        )

        validation = CrossValidationResult(
            finding_id=finding.id,
            primary_agent="agent",
            primary_model_provider="anthropic",
            validation_agent="validator",
            validator_model_provider="openai",
            primary_found=True,
            validator_found=True,
            consensus=ConsensusLevel.CONFIRMED,
            confidence_adjustment=0.3,  # Would push above 1.0
        )

        updated = manager._apply_cross_validation(
            [finding],
            [validation],
        )

        assert updated[0].calibrated_confidence == 1.0  # Clamped at 1.0

        # Very low confidence
        finding2 = FindingOutput(
            vulnerability_type=VulnerabilityType.OTHER,
            severity=SeverityLevel.LOW,
            file_path="test2.py",
            line_number=1,
            code_snippet="y = 2",
            description="Test2",
            confidence=0.1,
            agent_id="agent",
            blueprint_id="bp-1",
            finding_fingerprint="fp-test-002",
        )

        validation2 = CrossValidationResult(
            finding_id=finding2.id,
            primary_agent="agent",
            primary_model_provider="openai",
            validation_agent="validator",
            validator_model_provider="anthropic",
            primary_found=True,
            validator_found=False,
            consensus=ConsensusLevel.DISPUTED,
            confidence_adjustment=-0.3,  # Would push below 0.0
        )

        updated2 = manager._apply_cross_validation(
            [finding2],
            [validation2],
        )

        assert updated2[0].calibrated_confidence == 0.0  # Clamped at 0.0


class TestAgentRegistration:
    """Tests for agent registration and dispatch."""

    async def test_register_multiple_agents(self, fake_secrets):
        """Manager can register multiple agents."""
        manager = AuditManager(fake_secrets)

        agents = []
        for spec in [ISOSpecialization.SECURITY, ISOSpecialization.BUILDER,
                     ISOSpecialization.PERFORMANCE]:
            agent = MagicMock()
            agent.config = ISOConfig(
                specialization=spec,
                agent_id=f"{spec.value}-agent",
                model_provider=LLMProvider.ANTHROPIC,
                model_name="claude",
            )
            manager.register_agent(agent)
            agents.append(agent)

        assert len(manager._agents) == 3

    async def test_dispatch_agents_handles_partial_failures(self, fake_secrets):
        """Agent dispatch should handle some agents failing."""
        manager = AuditManager(fake_secrets)

        # One succeeds
        success_agent = MagicMock()
        success_agent.config = ISOConfig(
            specialization=ISOSpecialization.SECURITY,
            agent_id="success-agent",
            model_provider=LLMProvider.ANTHROPIC,
            model_name="claude",
        )
        success_batch = FindingBatch(
            blueprint_id="bp-1",
            findings=[],
            agent_id="success-agent",
            total_files_scanned=1,
            execution_duration_seconds=1.0,
        )
        success_agent.execute = AsyncMock(return_value=success_batch)

        # One fails
        fail_agent = MagicMock()
        fail_agent.config = ISOConfig(
            specialization=ISOSpecialization.BUILDER,
            agent_id="fail-agent",
            model_provider=LLMProvider.OPENAI,
            model_name="gpt-4o",
        )
        fail_agent.execute = AsyncMock(side_effect=RuntimeError("Failed"))

        manager.register_agent(success_agent)
        manager.register_agent(fail_agent)

        blueprints = {
            ISOSpecialization.SECURITY: Blueprint(
                id="bp-1",
                name="Test",
                description="Test",
                scope=BlueprintScope(
                    file_patterns=["*"],
                    check_types=[],
                    languages=["python"],
                ),
            ),
            ISOSpecialization.BUILDER: Blueprint(
                id="bp-2",
                name="Test",
                description="Test",
                scope=BlueprintScope(
                    file_patterns=["*"],
                    check_types=[],
                    languages=["python"],
                ),
            ),
        }

        request = AuditRequest(
            project_id=uuid4(),
            audit_run_id=uuid4(),
            file_contents={"app.py": "x = 1"},
            languages=["python"],
        )

        batches = await manager._dispatch_agents(request, blueprints)

        # Should return 1 successful batch (failure filtered out)
        assert len(batches) == 1
        assert batches[0].agent_id == "success-agent"
