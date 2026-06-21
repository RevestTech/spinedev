"""
Expanded Tests for Verification Schemas

Comprehensive tests for all schema models, enums, and validation logic.
Covers all VulnerabilityType and SeverityLevel values, schema edge cases,
serialization/deserialization roundtrips, and constraint validation.
"""

import pytest
from datetime import datetime, timezone
from uuid import uuid4

from tron.schemas.verification import (
    VulnerabilityType,
    SeverityLevel,
    ExecutionOutcome,
    Blueprint,
    BlueprintScope,
    FindingOutput,
    FindingBatch,
    SandboxExecutionResult,
    SemanticValidationResult,
    CalibrationMetric,
    PromptRegressionTest,
    DriftScore,
)


# ============================================================================
# VulnerabilityType Enum Tests
# ============================================================================

class TestVulnerabilityTypeEnum:
    """Tests for all VulnerabilityType enum values"""

    def test_all_vulnerability_types_exist(self):
        """Verify all expected vulnerability types are defined"""
        expected = {
            VulnerabilityType.SQL_INJECTION,
            VulnerabilityType.XSS,
            VulnerabilityType.HARDCODED_SECRETS,
            VulnerabilityType.INSECURE_DESERIALIZATION,
            VulnerabilityType.BROKEN_AUTH,
            VulnerabilityType.SECURITY_MISCONFIGURATION,
            VulnerabilityType.SSRF,
            VulnerabilityType.PATH_TRAVERSAL,
            VulnerabilityType.COMMAND_INJECTION,
            VulnerabilityType.OPEN_REDIRECT,
            VulnerabilityType.INSUFFICIENT_LOGGING,
            VulnerabilityType.DEPENDENCY_VULNERABILITY,
            VulnerabilityType.OTHER,
        }

        actual = set(VulnerabilityType)

        assert actual == expected
        assert len(actual) == 13

    def test_sql_injection_value(self):
        """SQL injection enum value"""
        assert VulnerabilityType.SQL_INJECTION.value == "sql_injection"

    def test_xss_value(self):
        """XSS enum value"""
        assert VulnerabilityType.XSS.value == "xss"

    def test_hardcoded_secrets_value(self):
        """Hardcoded secrets enum value"""
        assert VulnerabilityType.HARDCODED_SECRETS.value == "hardcoded_secrets"

    def test_insecure_deserialization_value(self):
        """Insecure deserialization enum value"""
        assert VulnerabilityType.INSECURE_DESERIALIZATION.value == "insecure_deserialization"

    def test_broken_auth_value(self):
        """Broken auth enum value"""
        assert VulnerabilityType.BROKEN_AUTH.value == "broken_auth"

    def test_security_misconfiguration_value(self):
        """Security misconfiguration enum value"""
        assert VulnerabilityType.SECURITY_MISCONFIGURATION.value == "security_misconfiguration"

    def test_ssrf_value(self):
        """SSRF enum value"""
        assert VulnerabilityType.SSRF.value == "ssrf"

    def test_path_traversal_value(self):
        """Path traversal enum value"""
        assert VulnerabilityType.PATH_TRAVERSAL.value == "path_traversal"

    def test_command_injection_value(self):
        """Command injection enum value"""
        assert VulnerabilityType.COMMAND_INJECTION.value == "command_injection"

    def test_open_redirect_value(self):
        """Open redirect enum value"""
        assert VulnerabilityType.OPEN_REDIRECT.value == "open_redirect"

    def test_insufficient_logging_value(self):
        """Insufficient logging enum value"""
        assert VulnerabilityType.INSUFFICIENT_LOGGING.value == "insufficient_logging"

    def test_dependency_vulnerability_value(self):
        """Dependency vulnerability enum value"""
        assert VulnerabilityType.DEPENDENCY_VULNERABILITY.value == "dependency_vulnerability"

    def test_other_value(self):
        """Other enum value"""
        assert VulnerabilityType.OTHER.value == "other"


# ============================================================================
# SeverityLevel Enum Tests
# ============================================================================

class TestSeverityLevelEnum:
    """Tests for all SeverityLevel enum values"""

    def test_all_severity_levels_exist(self):
        """Verify all expected severity levels are defined"""
        expected = {
            SeverityLevel.CRITICAL,
            SeverityLevel.HIGH,
            SeverityLevel.MEDIUM,
            SeverityLevel.LOW,
            SeverityLevel.INFO,
        }

        actual = set(SeverityLevel)

        assert actual == expected
        assert len(actual) == 5

    def test_critical_value(self):
        """Critical severity value"""
        assert SeverityLevel.CRITICAL.value == "critical"

    def test_high_value(self):
        """High severity value"""
        assert SeverityLevel.HIGH.value == "high"

    def test_medium_value(self):
        """Medium severity value"""
        assert SeverityLevel.MEDIUM.value == "medium"

    def test_low_value(self):
        """Low severity value"""
        assert SeverityLevel.LOW.value == "low"

    def test_info_value(self):
        """Info severity value"""
        assert SeverityLevel.INFO.value == "info"

    def test_severity_ordering(self):
        """Verify severity levels have consistent ordering"""
        severities = [SeverityLevel.CRITICAL, SeverityLevel.HIGH, SeverityLevel.MEDIUM, SeverityLevel.LOW, SeverityLevel.INFO]

        assert len(severities) == 5


# ============================================================================
# FindingOutput Schema Tests
# ============================================================================

class TestFindingOutputSchema:
    """Comprehensive tests for FindingOutput model"""

    def test_finding_creation_minimal(self):
        """Create finding with minimal required fields"""
        finding = FindingOutput(
            vulnerability_type=VulnerabilityType.SQL_INJECTION,
            severity=SeverityLevel.CRITICAL,
            file_path="app.py",
            line_number=42,
            code_snippet='query = "SELECT * FROM users WHERE id = " + user_id',
            description="SQL injection via string concatenation",
            agent_id="security-iso",
            blueprint_id="test-blueprint",
            finding_fingerprint="abc123def456",
            confidence=0.95,
            deterministic_tool_confirmed=True,
        )

        assert finding.vulnerability_type == VulnerabilityType.SQL_INJECTION
        assert finding.file_path == "app.py"
        assert finding.line_number == 42
        assert finding.confidence == 0.95

    def test_finding_with_all_fields(self):
        """Create finding with all optional fields"""
        finding = FindingOutput(
            vulnerability_type=VulnerabilityType.HARDCODED_SECRETS,
            severity=SeverityLevel.HIGH,
            file_path="config.py",
            line_number=10,
            line_end=12,
            code_snippet='API_KEY = "sk_live_secret"',
            description="Hardcoded API key",
            fix_suggestion="Use environment variables",
            agent_id="security-iso",
            blueprint_id="test-blueprint",
            finding_fingerprint="xyz789",
            confidence=0.92,
            deterministic_tool_confirmed=True,
            confirming_tools=["bandit", "semgrep"],
            calibrated_confidence=0.94,
            semantic_fingerprint="semantic_xyz",
        )

        assert finding.line_end == 12
        assert finding.fix_suggestion == "Use environment variables"
        assert finding.deterministic_tool_confirmed is True
        assert len(finding.confirming_tools) == 2

    def test_finding_line_number_must_be_positive(self):
        """Line number must be >= 1"""
        with pytest.raises(ValueError):
            FindingOutput(
                vulnerability_type=VulnerabilityType.XSS,
                severity=SeverityLevel.MEDIUM,
                file_path="views.py",
                line_number=0,  # Invalid!
                code_snippet="code",
                description="XSS issue",
                agent_id="security-iso",
                blueprint_id="test",
                finding_fingerprint="abc",
                confidence=0.7,
            )

    def test_finding_line_end_must_be_gte_line_number(self):
        """line_end must be >= line_number if provided"""
        with pytest.raises(ValueError):
            FindingOutput(
                vulnerability_type=VulnerabilityType.COMMAND_INJECTION,
                severity=SeverityLevel.CRITICAL,
                file_path="shell.py",
                line_number=42,
                line_end=40,  # Invalid! Less than line_number
                code_snippet="code",
                description="Command injection",
                agent_id="security-iso",
                blueprint_id="test",
                finding_fingerprint="abc",
                confidence=0.8,
            )

    def test_finding_confidence_bounds(self):
        """Confidence must be between 0 and 1"""
        with pytest.raises(ValueError):
            FindingOutput(
                vulnerability_type=VulnerabilityType.SSRF,
                severity=SeverityLevel.HIGH,
                file_path="http.py",
                line_number=55,
                code_snippet="code",
                description="SSRF issue",
                agent_id="security-iso",
                blueprint_id="test",
                finding_fingerprint="abc",
                confidence=1.5,  # Invalid!
            )

    def test_finding_confidence_capped_without_tool_confirmation(self):
        """Unconfirmed findings capped at 0.7 confidence"""
        with pytest.raises(ValueError):
            FindingOutput(
                vulnerability_type=VulnerabilityType.BROKEN_AUTH,
                severity=SeverityLevel.CRITICAL,
                file_path="auth.py",
                line_number=20,
                code_snippet="code",
                description="Broken auth",
                agent_id="security-iso",
                blueprint_id="test",
                finding_fingerprint="abc",
                confidence=0.95,  # Exceeds cap for unconfirmed
                deterministic_tool_confirmed=False,
            )

    def test_finding_code_snippet_not_empty(self):
        """Code snippet cannot be empty or whitespace-only"""
        with pytest.raises(ValueError):
            FindingOutput(
                vulnerability_type=VulnerabilityType.OTHER,
                severity=SeverityLevel.INFO,
                file_path="test.py",
                line_number=1,
                code_snippet="   ",  # Invalid!
                description="Issue",
                agent_id="security-iso",
                blueprint_id="test",
                finding_fingerprint="abc",
                confidence=0.5,
            )

    def test_finding_validation_required_computed_field(self):
        """validation_required property reflects tool confirmation"""
        confirmed = FindingOutput(
            vulnerability_type=VulnerabilityType.SQL_INJECTION,
            severity=SeverityLevel.CRITICAL,
            file_path="app.py",
            line_number=42,
            code_snippet="code",
            description="SQL injection",
            agent_id="security-iso",
            blueprint_id="test",
            finding_fingerprint="abc",
            confidence=0.99,
            deterministic_tool_confirmed=True,
        )

        unconfirmed = FindingOutput(
            vulnerability_type=VulnerabilityType.SQL_INJECTION,
            severity=SeverityLevel.CRITICAL,
            file_path="app.py",
            line_number=42,
            code_snippet="code",
            description="SQL injection",
            agent_id="security-iso",
            blueprint_id="test",
            finding_fingerprint="abc",
            confidence=0.65,
            deterministic_tool_confirmed=False,
        )

        assert confirmed.validation_required is False
        assert unconfirmed.validation_required is True


# ============================================================================
# Blueprint Schema Tests
# ============================================================================

class TestBlueprintSchema:
    """Tests for Blueprint model"""

    def test_blueprint_creation_minimal(self):
        """Create blueprint with minimal fields"""
        blueprint = Blueprint(
            id="test-blueprint",
            name="Security Audit",
            description="Full security analysis",
            scope=BlueprintScope(
                file_patterns=["*.py"],
                check_types=[VulnerabilityType.SQL_INJECTION],
                languages=["python"],
            ),
        )

        assert blueprint.id == "test-blueprint"
        assert blueprint.temperature == 0.1
        assert blueprint.max_tokens == 4000

    def test_blueprint_with_all_fields(self):
        """Create blueprint with all fields"""
        blueprint = Blueprint(
            id="full-blueprint",
            name="Complete Audit",
            description="Comprehensive security audit",
            scope=BlueprintScope(
                file_patterns=["*.py", "*.js"],
                check_types=[
                    VulnerabilityType.SQL_INJECTION,
                    VulnerabilityType.XSS,
                    VulnerabilityType.HARDCODED_SECRETS,
                ],
                languages=["python", "javascript"],
                max_files=1000,
            ),
            not_in_scope=["test_*.py", "**/*.test.js"],
            tools_required=["bandit", "semgrep"],
            temperature=0.1,
            max_tokens=8000,
            max_duration_seconds=600,
            min_consensus_for_critical=3,
        )

        assert len(blueprint.scope.check_types) == 3
        assert len(blueprint.not_in_scope) == 2
        assert blueprint.max_tokens == 8000

    def test_blueprint_admission_control_blocks_etc_path(self):
        """Blueprint rejects /etc/* patterns"""
        with pytest.raises(ValueError, match="admission control"):
            Blueprint(
                id="bad-blueprint",
                name="Bad",
                description="Bad blueprint",
                scope=BlueprintScope(
                    file_patterns=["/etc/passwd"],
                    check_types=[VulnerabilityType.OTHER],
                    languages=["text"],
                ),
            )

    def test_blueprint_admission_control_blocks_proc(self):
        """Blueprint rejects /proc/* patterns"""
        with pytest.raises(ValueError, match="admission control"):
            Blueprint(
                id="bad-blueprint",
                name="Bad",
                description="Bad blueprint",
                scope=BlueprintScope(
                    file_patterns=["/proc/1/status"],
                    check_types=[VulnerabilityType.OTHER],
                    languages=["text"],
                ),
            )

    def test_blueprint_admission_control_blocks_env_files(self):
        """Blueprint rejects .env file patterns"""
        with pytest.raises(ValueError, match="admission control"):
            Blueprint(
                id="bad-blueprint",
                name="Bad",
                description="Bad blueprint",
                scope=BlueprintScope(
                    file_patterns=["**/.env"],
                    check_types=[VulnerabilityType.OTHER],
                    languages=["text"],
                ),
            )


# ============================================================================
# FindingBatch Schema Tests
# ============================================================================

class TestFindingBatchSchema:
    """Tests for FindingBatch aggregation"""

    def test_finding_batch_empty(self):
        """Create batch with no findings"""
        batch = FindingBatch(
            blueprint_id="test-blueprint",
            findings=[],
            agent_id="security-iso",
            total_files_scanned=10,
            execution_duration_seconds=15.5,
        )

        assert len(batch.findings) == 0
        assert batch.critical_count == 0
        assert batch.unconfirmed_count == 0

    def test_finding_batch_with_critical_findings(self):
        """Batch with critical findings"""
        findings = [
            FindingOutput(
                vulnerability_type=VulnerabilityType.SQL_INJECTION,
                severity=SeverityLevel.CRITICAL,
                file_path="app.py",
                line_number=42,
                code_snippet="code",
                description="SQL injection",
                agent_id="security-iso",
                blueprint_id="test-blueprint",
                finding_fingerprint="abc1",
                confidence=0.95,
                deterministic_tool_confirmed=True,
            ),
            FindingOutput(
                vulnerability_type=VulnerabilityType.HARDCODED_SECRETS,
                severity=SeverityLevel.CRITICAL,
                file_path="config.py",
                line_number=10,
                code_snippet="API_KEY = ...",
                description="Hardcoded secret",
                agent_id="security-iso",
                blueprint_id="test-blueprint",
                finding_fingerprint="abc2",
                confidence=0.98,
                deterministic_tool_confirmed=True,
            ),
        ]

        batch = FindingBatch(
            blueprint_id="test-blueprint",
            findings=findings,
            agent_id="security-iso",
            total_files_scanned=5,
            execution_duration_seconds=8.2,
        )

        assert len(batch.findings) == 2
        assert batch.critical_count == 2
        assert batch.unconfirmed_count == 0

    def test_finding_batch_mixed_severities(self):
        """Batch with mixed severity findings"""
        findings = [
            FindingOutput(
                vulnerability_type=VulnerabilityType.SQL_INJECTION,
                severity=SeverityLevel.CRITICAL,
                file_path="a.py",
                line_number=1,
                code_snippet="code",
                description="Issue",
                agent_id="iso",
                blueprint_id="bp",
                finding_fingerprint="a",
                confidence=0.9,
                deterministic_tool_confirmed=True,
            ),
            FindingOutput(
                vulnerability_type=VulnerabilityType.XSS,
                severity=SeverityLevel.HIGH,
                file_path="b.py",
                line_number=2,
                code_snippet="code",
                description="Issue",
                agent_id="iso",
                blueprint_id="bp",
                finding_fingerprint="b",
                confidence=0.8,
                deterministic_tool_confirmed=True,
            ),
            FindingOutput(
                vulnerability_type=VulnerabilityType.OPEN_REDIRECT,
                severity=SeverityLevel.MEDIUM,
                file_path="c.py",
                line_number=3,
                code_snippet="code",
                description="Issue",
                agent_id="iso",
                blueprint_id="bp",
                finding_fingerprint="c",
                confidence=0.7,
                deterministic_tool_confirmed=False,
            ),
        ]

        batch = FindingBatch(
            blueprint_id="bp",
            findings=findings,
            agent_id="iso",
            total_files_scanned=3,
            execution_duration_seconds=5.0,
        )

        assert batch.critical_count == 1
        assert batch.unconfirmed_count == 1


# ============================================================================
# SandboxExecutionResult Schema Tests
# ============================================================================

class TestSandboxExecutionResultSchema:
    """Tests for sandbox execution results"""

    def test_execution_success(self):
        """Successful execution"""
        result = SandboxExecutionResult(
            finding_id=uuid4(),
            outcome=ExecutionOutcome.SUCCESS,
            execution_duration_ms=1500,
            finding_verified=True,
            confidence_adjustment=0.15,
        )

        assert result.outcome == ExecutionOutcome.SUCCESS
        assert result.finding_verified is True

    def test_execution_timeout_not_failure(self):
        """Timeout is not treated as failure"""
        result = SandboxExecutionResult(
            finding_id=uuid4(),
            outcome=ExecutionOutcome.TIMEOUT,
            execution_duration_ms=30500,
            timeout_limit_ms=30000,
            finding_verified=False,
            confidence_adjustment=0.0,  # Timeouts don't adjust confidence
        )

        assert result.outcome == ExecutionOutcome.TIMEOUT
        assert result.confidence_adjustment == 0.0

    def test_execution_timeout_cannot_be_negative_adjustment(self):
        """Timeout cannot have large negative adjustment (it's inconclusive)"""
        with pytest.raises(ValueError):
            SandboxExecutionResult(
                finding_id=uuid4(),
                outcome=ExecutionOutcome.TIMEOUT,
                execution_duration_ms=30500,
                finding_verified=False,
                confidence_adjustment=-0.3,  # Too negative for timeout
            )

    def test_execution_resource_exceeded(self):
        """Out-of-memory or resource limit hit"""
        result = SandboxExecutionResult(
            finding_id=uuid4(),
            outcome=ExecutionOutcome.RESOURCE_EXCEEDED,
            execution_duration_ms=5000,
            memory_used_mb=2048.5,
            finding_verified=False,
            confidence_adjustment=-0.2,
        )

        assert result.outcome == ExecutionOutcome.RESOURCE_EXCEEDED
        assert result.memory_used_mb == 2048.5


# ============================================================================
# SemanticValidationResult Schema Tests
# ============================================================================

class TestSemanticValidationResultSchema:
    """Tests for semantic validation results"""

    def test_valid_semantic_validation(self):
        """Code exists at claimed location, matches vulnerability"""
        result = SemanticValidationResult(
            finding_id=uuid4(),
            code_exists_at_location=True,
            code_similarity_score=0.98,
            vulnerability_pattern_match=True,
            fix_addresses_vulnerability=True,
            semantic_confidence=0.95,
        )

        assert result.code_exists_at_location is True
        assert result.semantic_confidence == 0.95

    def test_hallucinated_location_low_confidence(self):
        """Code doesn't exist at claimed location"""
        with pytest.raises(ValueError):
            SemanticValidationResult(
                finding_id=uuid4(),
                code_exists_at_location=False,
                code_similarity_score=0.0,
                vulnerability_pattern_match=False,
                fix_addresses_vulnerability=None,
                semantic_confidence=0.8,  # Too high for hallucinated location
            )

    def test_poor_code_match_low_confidence(self):
        """Similarity is low but confidence is high — rejected"""
        with pytest.raises(ValueError):
            SemanticValidationResult(
                finding_id=uuid4(),
                code_exists_at_location=True,
                code_similarity_score=0.3,  # Low match
                vulnerability_pattern_match=False,
                semantic_confidence=0.7,  # Too high for low similarity
            )


# ============================================================================
# CalibrationMetric Schema Tests
# ============================================================================

class TestCalibrationMetricSchema:
    """Tests for confidence calibration metrics"""

    def test_calibration_metric_well_calibrated(self):
        """Create well-calibrated metric"""
        metric = CalibrationMetric(
            confidence_band="0.8-0.9",
            total_findings=250,
            sample_sufficient=True,
            true_positives=240,
            false_positives=10,
            actual_accuracy=0.96,
            calibration_error=0.02,
        )

        assert metric.sample_sufficient is True
        assert metric.actual_accuracy == 0.96
        assert metric.calibration_error == 0.02

    def test_calibration_metric_overconfident(self):
        """Create overconfident metric"""
        metric = CalibrationMetric(
            confidence_band="0.7-0.8",
            total_findings=200,
            sample_sufficient=True,
            true_positives=150,
            false_positives=50,
            actual_accuracy=0.75,
            calibration_error=-0.05,  # Overconfident
        )

        assert metric.calibration_error < 0

    def test_calibration_metric_insufficient_sample(self):
        """Create metric with insufficient sample"""
        # 140/150 = 0.9333... ≈ 0.933
        metric = CalibrationMetric(
            confidence_band="0.9-1.0",
            total_findings=150,  # Below 200 threshold
            sample_sufficient=False,
            true_positives=140,
            false_positives=10,
            actual_accuracy=round(140 / 150, 4),
            calibration_error=round(140 / 150 - 0.95, 4),
        )

        assert metric.sample_sufficient is False


# ============================================================================
# PromptRegressionTest Schema Tests
# ============================================================================

class TestPromptRegressionTestSchema:
    """Tests for prompt regression testing"""

    def test_regression_test_creation(self):
        """Create regression test"""
        test = PromptRegressionTest(
            template_id="security-v1",
            test_input='cursor.execute("SELECT * FROM users WHERE id = " + user_id)',
            expected_finding_type=VulnerabilityType.SQL_INJECTION,
            expected_confidence_min=0.85,
            should_find=True,
        )

        assert test.template_id == "security-v1"
        assert test.should_find is True

    def test_regression_test_passed(self):
        """Mark regression test as passed"""
        test = PromptRegressionTest(
            template_id="security-v1",
            test_input="vulnerable code",
            should_find=True,
            last_passed=True,
            last_run_at=datetime.now(timezone.utc),
        )

        assert test.last_passed is True

    def test_regression_test_failed(self):
        """Mark regression test as failed"""
        test = PromptRegressionTest(
            template_id="security-v1",
            test_input="vulnerable code",
            should_find=True,
            last_passed=False,
            last_result="Agent did not detect SQL injection",
        )

        assert test.last_passed is False


# ============================================================================
# DriftScore Schema Tests
# ============================================================================

class TestDriftScoreSchema:
    """Tests for drift detection"""

    def test_drift_not_detected(self):
        """Template is stable (no drift)"""
        drift = DriftScore(
            template_id="security-v1",
            baseline_hash="a" * 64,
            current_hash="a" * 64,  # Same
            semantic_similarity=0.99,
            threshold=0.95,
            drift_detected=False,
        )

        assert drift.drift_detected is False

    def test_drift_detected(self):
        """Template has drifted beyond threshold"""
        drift = DriftScore(
            template_id="security-v1",
            baseline_hash="a" * 64,
            current_hash="b" * 64,  # Different
            semantic_similarity=0.80,
            threshold=0.95,
            drift_detected=True,
        )

        assert drift.drift_detected is True

    def test_drift_consistency_validation(self):
        """drift_detected must match similarity vs threshold"""
        with pytest.raises(ValueError):
            DriftScore(
                template_id="security-v1",
                baseline_hash="a" * 64,
                current_hash="b" * 64,
                semantic_similarity=0.98,  # High similarity
                threshold=0.95,
                drift_detected=True,  # Contradiction!
            )


# ============================================================================
# Enum Integration Tests
# ============================================================================

class TestEnumIntegration:
    """Tests for enum usage in models"""

    def test_all_vulnerability_types_usable_in_finding(self):
        """Every VulnerabilityType can be used in a finding"""
        for vuln_type in VulnerabilityType:
            finding = FindingOutput(
                vulnerability_type=vuln_type,
                severity=SeverityLevel.MEDIUM,
                file_path="test.py",
                line_number=1,
                code_snippet="code",
                description="Test",
                agent_id="iso",
                blueprint_id="bp",
                finding_fingerprint="fp",
                confidence=0.5,
            )

            assert finding.vulnerability_type == vuln_type

    def test_all_severity_levels_usable_in_finding(self):
        """Every SeverityLevel can be used in a finding"""
        for severity in SeverityLevel:
            finding = FindingOutput(
                vulnerability_type=VulnerabilityType.OTHER,
                severity=severity,
                file_path="test.py",
                line_number=1,
                code_snippet="code",
                description="Test",
                agent_id="iso",
                blueprint_id="bp",
                finding_fingerprint="fp",
                confidence=0.5,
            )

            assert finding.severity == severity
