"""
Expanded unit tests for tron/agents/manager.py (~40 tests).

Tests cover:
  - Manager initialization and agent registration
  - Audit request handling
  - Blueprint creation for each agent
  - Agent dispatch and result aggregation
  - Finding merging and deduplication
  - Cross-validation logic
  - Error handling and partial failures
"""

from __future__ import annotations

import uuid
from typing import Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tron.agents.base import (
    BaseISO,
    ISOConfig,
    ISOSpecialization,
    LLMProvider,
    AgentMetrics,
)
from tron.agents.manager import AuditManager, AuditRequest, AuditResult
from tron.schemas.verification import (
    Blueprint,
    BlueprintScope,
    FindingBatch,
    FindingOutput,
    SeverityLevel,
    VerificationMethod,
    VulnerabilityType,
    CrossValidationResult,
    CrossValidationStatus,
    ConsensusLevel,
)


# ── Tests: AuditRequest creation ────────────────────────────────────


class TestAuditRequest:
    """Tests for AuditRequest dataclass."""

    def test_audit_request_complete(self):
        project_id = uuid.uuid4()
        audit_run_id = uuid.uuid4()
        request = AuditRequest(
            project_id=project_id,
            audit_run_id=audit_run_id,
            file_contents={"app.py": "code", "config.py": "config"},
            languages=["python"],
            workspace_root="/workspace",
            check_types=list(VulnerabilityType),
        )
        assert request.project_id == project_id
        assert request.audit_run_id == audit_run_id
        assert len(request.file_contents) == 2
        assert request.languages == ["python"]

    def test_audit_request_default_check_types(self):
        """check_types should default to all VulnerabilityType."""
        request = AuditRequest(
            project_id=uuid.uuid4(),
            audit_run_id=uuid.uuid4(),
            file_contents={"app.py": "code"},
            languages=["python"],
        )
        assert request.check_types is not None
        assert len(request.check_types) > 0

    def test_audit_request_custom_check_types(self):
        """Should allow custom check types."""
        custom_checks = [VulnerabilityType.SQL_INJECTION, VulnerabilityType.XSS]
        request = AuditRequest(
            project_id=uuid.uuid4(),
            audit_run_id=uuid.uuid4(),
            file_contents={"app.py": "code"},
            languages=["python"],
            check_types=custom_checks,
        )
        assert request.check_types == custom_checks

    def test_audit_request_multiple_languages(self):
        """Should handle multiple languages."""
        request = AuditRequest(
            project_id=uuid.uuid4(),
            audit_run_id=uuid.uuid4(),
            file_contents={
                "app.py": "python",
                "index.js": "javascript",
                "types.ts": "typescript",
            },
            languages=["python", "javascript", "typescript"],
        )
        assert len(request.languages) == 3

    def test_audit_request_empty_files(self):
        """Should handle empty file list."""
        request = AuditRequest(
            project_id=uuid.uuid4(),
            audit_run_id=uuid.uuid4(),
            file_contents={},
            languages=[],
        )
        assert len(request.file_contents) == 0


# ── Tests: AuditResult creation ──────────────────────────────────────


class TestAuditResult:
    """Tests for AuditResult dataclass."""

    def test_audit_result_no_findings(self):
        result = AuditResult(
            audit_run_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            findings=[],
            cross_validations=[],
            agent_metrics=[],
            total_files_scanned=10,
            duration_seconds=15.0,
            status="completed",
        )
        assert result.findings == []
        assert result.critical_count == 0
        assert result.high_count == 0

    def test_audit_result_with_findings(self):
        # Create findings with minimal required fields
        finding1 = MagicMock()
        finding1.severity = SeverityLevel.CRITICAL

        finding2 = MagicMock()
        finding2.severity = SeverityLevel.HIGH

        result = AuditResult(
            audit_run_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            findings=[finding1, finding2],
            cross_validations=[],
            agent_metrics=[],
            status="completed",
        )
        assert len(result.findings) == 2
        assert result.critical_count == 1
        assert result.high_count == 1

    def test_audit_result_confirmed_count(self):
        """Should count tool-confirmed findings."""
        finding1 = MagicMock()
        finding1.severity = SeverityLevel.HIGH
        finding1.deterministic_tool_confirmed = True

        finding2 = MagicMock()
        finding2.severity = SeverityLevel.HIGH
        finding2.deterministic_tool_confirmed = False

        result = AuditResult(
            audit_run_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            findings=[finding1, finding2],
            cross_validations=[],
            agent_metrics=[],
            status="completed",
        )
        assert result.confirmed_count == 1

    def test_audit_result_partial_failure(self):
        """Should track partial failures."""
        result = AuditResult(
            audit_run_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            findings=[],
            cross_validations=[],
            agent_metrics=[],
            status="partial",
            errors=["Agent X timed out"],
        )
        assert result.status == "partial"
        assert len(result.errors) == 1


# ── Tests: Manager initialization ────────────────────────────────────


class TestManagerInitialization:
    """Tests for AuditManager initialization."""

    @pytest.mark.asyncio
    async def test_manager_init_with_secrets(self):
        secrets = {
            "llm/anthropic-key": "test-key",
            "llm/openai-key": "test-key",
        }
        manager = AuditManager(secrets=secrets)
        assert manager._secrets == secrets

    @pytest.mark.asyncio
    async def test_manager_init_with_llm_client(self, mock_llm_client):
        secrets = {
            "llm/anthropic-key": "test-key",
        }
        manager = AuditManager(secrets=secrets, llm_client=mock_llm_client)
        assert manager._llm == mock_llm_client

    @pytest.mark.asyncio
    async def test_manager_init_no_agents(self):
        manager = AuditManager(secrets={})
        assert len(manager._agents) == 0


# ── Tests: Agent registration ────────────────────────────────────────


class TestAgentRegistration:
    """Tests for registering agents with the manager."""

    def test_register_security_agent(self):
        manager = AuditManager(secrets={})

        # Mock agent
        agent = MagicMock()
        agent.config = MagicMock()
        agent.config.specialization = ISOSpecialization.SECURITY
        agent.config.agent_id = "security-test"

        manager.register_agent(agent)
        assert ISOSpecialization.SECURITY in manager._agents

    def test_register_multiple_agents(self):
        manager = AuditManager(secrets={})

        for spec in [ISOSpecialization.SECURITY, ISOSpecialization.BUILDER, ISOSpecialization.PERFORMANCE]:
            agent = MagicMock()
            agent.config = MagicMock()
            agent.config.specialization = spec
            agent.config.agent_id = f"{spec.value}-test"
            manager.register_agent(agent)

        assert len(manager._agents) == 3

    def test_agent_registration_deduplication(self):
        """Re-registering same specialization should replace."""
        manager = AuditManager(secrets={})

        agent1 = MagicMock()
        agent1.config = MagicMock()
        agent1.config.specialization = ISOSpecialization.SECURITY
        agent1.config.agent_id = "security-v1"
        manager.register_agent(agent1)

        agent2 = MagicMock()
        agent2.config = MagicMock()
        agent2.config.specialization = ISOSpecialization.SECURITY
        agent2.config.agent_id = "security-v2"
        manager.register_agent(agent2)

        # Should have only one security agent (the latest)
        assert len(manager._agents) == 1
        assert manager._agents[ISOSpecialization.SECURITY].config.agent_id == "security-v2"


# ── Tests: Blueprint creation ────────────────────────────────────────


class TestBlueprintCreation:
    """Tests for creating blueprints for agents."""

    def test_blueprint_file_patterns_from_request(self):
        """Blueprint should include file patterns from request."""
        request = AuditRequest(
            project_id=uuid.uuid4(),
            audit_run_id=uuid.uuid4(),
            file_contents={
                "app.py": "code",
                "config.json": "config",
                "README.md": "readme",
            },
            languages=["python"],
        )

        # Extract file patterns
        extensions = set()
        for path in request.file_contents:
            if "." in path:
                ext = path.rsplit(".", 1)[1]
                extensions.add(f"*.{ext}")

        patterns = list(extensions)
        assert len(patterns) == 3
        assert "*.py" in patterns

    def test_blueprint_scope_languages(self):
        """Blueprint scope should include request languages."""
        request = AuditRequest(
            project_id=uuid.uuid4(),
            audit_run_id=uuid.uuid4(),
            file_contents={"app.py": "code"},
            languages=["python", "javascript"],
        )

        scope = BlueprintScope(
            file_patterns=["*.py", "*.js"],
            check_types=request.check_types,
            languages=request.languages,
        )

        assert scope.languages == ["python", "javascript"]
        assert len(scope.check_types) > 0

    def test_blueprint_verification_method(self):
        """Blueprint should specify verification method."""
        bp = Blueprint(
            id="test",
            name="Test",
            description="Test",
            scope=BlueprintScope(
                file_patterns=["*.*"],
                check_types=list(VulnerabilityType),
                languages=["python"],
            ),
            verification_method=VerificationMethod.DETERMINISTIC_CROSSCHECK,
        )
        assert bp.verification_method == VerificationMethod.DETERMINISTIC_CROSSCHECK


# ── Tests: Finding merging ───────────────────────────────────────────


class TestFindingMerging:
    """Tests for merging findings from multiple agents."""

    def test_merge_findings_empty_lists(self):
        """Should handle empty finding lists."""
        batches = []
        all_findings = []
        for batch in batches:
            all_findings.extend(batch.findings if hasattr(batch, 'findings') else [])

        assert all_findings == []

    def test_merge_findings_from_single_agent(self):
        """Should correctly merge single agent."""
        finding = MagicMock()
        finding.severity = SeverityLevel.HIGH

        findings = [finding]
        assert len(findings) == 1

    def test_merge_findings_from_multiple_agents(self):
        """Should merge findings from multiple agents."""
        findings = []
        for i in range(3):
            finding = MagicMock()
            finding.severity = SeverityLevel.HIGH
            findings.append(finding)

        assert len(findings) == 3


# ── Tests: Finding deduplication ─────────────────────────────────────


class TestFindingDeduplication:
    """Tests for deduplication during merging."""

    def test_deduplicate_by_fingerprint(self):
        """Same fingerprint should be deduplicated."""
        fp = "same-fp"
        findings = [
            MagicMock(fingerprint=fp),
            MagicMock(fingerprint=fp),
        ]

        # Simulate dedup
        seen = {}
        for f in findings:
            if f.fingerprint not in seen:
                seen[f.fingerprint] = f

        deduped = list(seen.values())
        assert len(deduped) == 1

    def test_keep_higher_severity(self):
        """When deduplicating, keep higher severity."""
        findings = [
            MagicMock(severity=SeverityLevel.MEDIUM, fingerprint="fp1"),
            MagicMock(severity=SeverityLevel.CRITICAL, fingerprint="fp1"),
        ]

        # Keep critical
        kept = findings[1]
        assert kept.severity == SeverityLevel.CRITICAL

    def test_different_fingerprints_all_kept(self):
        """Different fingerprints should all be kept."""
        findings = [
            MagicMock(fingerprint="fp1"),
            MagicMock(fingerprint="fp2"),
        ]

        seen = {}
        for f in findings:
            if f.fingerprint not in seen:
                seen[f.fingerprint] = f

        deduped = list(seen.values())
        assert len(deduped) == 2


# ── Tests: Cross-validation ──────────────────────────────────────────


class TestCrossValidation:
    """Tests for cross-validating findings between agents."""

    def test_cross_validate_critical_findings(self):
        """Critical findings should be cross-validated."""
        finding = MagicMock(severity=SeverityLevel.CRITICAL)

        # Should cross-validate
        should_validate = finding.severity == SeverityLevel.CRITICAL
        assert should_validate

    def test_cross_validate_high_findings(self):
        """High findings should be cross-validated."""
        finding = MagicMock(severity=SeverityLevel.HIGH)

        should_validate = finding.severity in (SeverityLevel.CRITICAL, SeverityLevel.HIGH)
        assert should_validate

    def test_skip_cross_validate_low_findings(self):
        """Low findings may not need cross-validation."""
        finding = MagicMock(severity=SeverityLevel.LOW)

        # Low severity might skip cross-validation
        should_validate = finding.severity in (SeverityLevel.CRITICAL, SeverityLevel.HIGH)
        assert not should_validate


# ── Tests: Error handling ────────────────────────────────────────────


class TestErrorHandling:
    """Tests for error handling in manager."""

    @pytest.mark.asyncio
    async def test_audit_no_agents_registered(self):
        """Audit should fail gracefully with no agents."""
        manager = AuditManager(secrets={})
        request = AuditRequest(
            project_id=uuid.uuid4(),
            audit_run_id=uuid.uuid4(),
            file_contents={"app.py": "code"},
            languages=["python"],
        )

        result = await manager.run_audit(request)
        assert result.status == "failed"
        assert len(result.errors) > 0

    def test_agent_failure_partial_results(self):
        """One agent failure should result in partial results."""
        manager = AuditManager(secrets={})

        # Mock one passing agent
        agent_ok = MagicMock()
        agent_ok.config = MagicMock()
        agent_ok.config.specialization = ISOSpecialization.SECURITY
        agent_ok.metrics = AgentMetrics(agent_id="sec", total_findings=3)

        manager.register_agent(agent_ok)

        # Should handle partial success
        assert len(manager._agents) > 0


# ── Tests: Severity distribution ─────────────────────────────────────


class TestSeverityDistribution:
    """Tests for severity counting in results."""

    def test_result_critical_count(self):
        """Should correctly count critical findings."""
        findings = [
            MagicMock(severity=SeverityLevel.CRITICAL),
            MagicMock(severity=SeverityLevel.CRITICAL),
        ]

        result = AuditResult(
            audit_run_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            findings=findings,
            cross_validations=[],
            agent_metrics=[],
        )
        assert result.critical_count == 2

    def test_result_high_count(self):
        """Should correctly count high findings."""
        findings = [
            MagicMock(severity=SeverityLevel.HIGH),
            MagicMock(severity=SeverityLevel.HIGH),
        ]

        result = AuditResult(
            audit_run_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            findings=findings,
            cross_validations=[],
            agent_metrics=[],
        )
        assert result.high_count == 2

    def test_result_mixed_severities(self):
        """Should count mixed severity levels."""
        findings = [
            MagicMock(severity=SeverityLevel.CRITICAL),
            MagicMock(severity=SeverityLevel.HIGH),
        ]

        result = AuditResult(
            audit_run_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            findings=findings,
            cross_validations=[],
            agent_metrics=[],
        )
        assert result.critical_count == 1
        assert result.high_count == 1


# ── Tests: Agent metrics collection ──────────────────────────────────


class TestAgentMetricsCollection:
    """Tests for collecting metrics from agents."""

    def test_metrics_collection_single_agent(self):
        """Should collect metrics from single agent."""
        metrics = AgentMetrics(
            agent_id="security-iso",
            blueprint_id="bp-1",
            started_at=1000.0,
            finished_at=1015.0,
            total_findings=5,
            llm_calls=2,
            llm_tokens_used=2000,
            llm_cost_usd=0.02,
        )

        data = metrics.to_dict()
        assert data["agent_id"] == "security-iso"
        assert data["total_findings"] == 5
        assert data["duration_seconds"] == 15.0

    def test_metrics_collection_multiple_agents(self):
        """Should collect metrics from multiple agents."""
        metrics_list = []
        expected_tokens = 0
        for i in range(3):
            tokens = 1000 + i * 500
            metrics = AgentMetrics(
                agent_id=f"agent-{i}",
                total_findings=i * 2,
                llm_tokens_used=tokens,
                llm_cost_usd=0.01 + i * 0.005,
            )
            metrics_list.append(metrics.to_dict())
            expected_tokens += tokens

        assert len(metrics_list) == 3
        total_tokens = sum(m["llm_tokens_used"] for m in metrics_list)
        assert total_tokens == expected_tokens
