"""
Unit tests for verification.py schemas — Pydantic models and validators.

Covers:
  - FindingOutput validators and computed properties
  - CrossValidationResult validators and properties
  - SandboxExecutionResult timeout/error handling
  - SemanticValidationResult code validation
  - CalibrationMetric accuracy calculation
  - PromptRegressionTest __str__ with status
  - DriftScore validation and __str__
  - FindingBatch computed properties
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from tron.schemas.verification import (
    FindingOutput,
    CrossValidationResult,
    SandboxExecutionResult,
    SemanticValidationResult,
    CalibrationMetric,
    PromptRegressionTest,
    DriftScore,
    FindingBatch,
    VulnerabilityType,
    SeverityLevel,
    ExecutionOutcome,
    ConsensusLevel,
)


class TestFindingOutputValidators:
    """Tests for FindingOutput field validators."""

    def test_validate_code_snippet_empty_raises(self):
        """Empty code_snippet should raise ValueError."""
        with pytest.raises(ValueError, match="String should have at least 1 character"):
            FindingOutput(
                vulnerability_type=VulnerabilityType.SQL_INJECTION,
                severity=SeverityLevel.HIGH,
                file_path="app.py",
                line_number=10,
                code_snippet="",
                description="Test",
                confidence=0.6,
                agent_id="test-agent",
                blueprint_id="test-bp",
                finding_fingerprint="abc123",
            )

    def test_validate_code_snippet_whitespace_only_raises(self):
        """Whitespace-only code_snippet should raise ValueError."""
        with pytest.raises(ValueError, match="String should have at least 1 character"):
            FindingOutput(
                vulnerability_type=VulnerabilityType.XSS,
                severity=SeverityLevel.MEDIUM,
                file_path="index.js",
                line_number=5,
                code_snippet="   \n\t  ",  # Whitespace-only, stripped to empty by Pydantic
                description="Test",
                confidence=0.7,
                agent_id="test-agent",
                blueprint_id="test-bp",
                finding_fingerprint="def456",
            )

    def test_validate_line_number_zero_raises(self):
        """line_number=0 should raise ValueError."""
        with pytest.raises(ValueError, match="Input should be greater than 0"):
            FindingOutput(
                vulnerability_type=VulnerabilityType.PATH_TRAVERSAL,
                severity=SeverityLevel.HIGH,
                file_path="app.py",
                line_number=0,
                code_snippet="bad code",
                description="Test",
                confidence=0.6,
                agent_id="test-agent",
                blueprint_id="test-bp",
                finding_fingerprint="ghi789",
            )

    def test_validate_line_number_negative_raises(self):
        """Negative line_number should raise ValueError."""
        with pytest.raises(ValueError, match="Input should be greater than 0"):
            FindingOutput(
                vulnerability_type=VulnerabilityType.COMMAND_INJECTION,
                severity=SeverityLevel.CRITICAL,
                file_path="app.py",
                line_number=-1,
                code_snippet="bad",
                description="Test",
                confidence=0.5,
                agent_id="test-agent",
                blueprint_id="test-bp",
                finding_fingerprint="jkl012",
            )

    def test_validate_line_end_less_than_line_number_raises(self):
        """line_end < line_number should raise ValueError."""
        with pytest.raises(ValueError, match="line_end must be greater than or equal to line_number"):
            FindingOutput(
                vulnerability_type=VulnerabilityType.HARDCODED_SECRETS,
                severity=SeverityLevel.HIGH,
                file_path="config.py",
                line_number=10,
                line_end=5,
                code_snippet="secret = 'abc'",
                description="Test",
                confidence=0.7,
                agent_id="test-agent",
                blueprint_id="test-bp",
                finding_fingerprint="mno345",
            )

    def test_validate_line_end_equal_to_line_number_succeeds(self):
        """line_end == line_number should succeed."""
        finding = FindingOutput(
            vulnerability_type=VulnerabilityType.BROKEN_AUTH,
            severity=SeverityLevel.MEDIUM,
            file_path="auth.py",
            line_number=15,
            line_end=15,
            code_snippet="if user:",
            description="Test",
            confidence=0.6,
            agent_id="test-agent",
            blueprint_id="test-bp",
            finding_fingerprint="pqr678",
        )
        assert finding.line_end == 15

    def test_validate_confidence_capped_at_0_7_when_not_confirmed(self):
        """confidence > 0.7 when deterministic_tool_confirmed=False should raise."""
        with pytest.raises(ValueError, match="confidence must be capped at 0.7"):
            FindingOutput(
                vulnerability_type=VulnerabilityType.SSRF,
                severity=SeverityLevel.HIGH,
                file_path="app.py",
                line_number=20,
                code_snippet="requests.get(url)",
                description="Test",
                confidence=0.8,
                deterministic_tool_confirmed=False,
                agent_id="test-agent",
                blueprint_id="test-bp",
                finding_fingerprint="stu901",
            )

    def test_validate_confidence_0_7_allowed_when_not_confirmed(self):
        """confidence=0.7 should be allowed when deterministic_tool_confirmed=False."""
        finding = FindingOutput(
            vulnerability_type=VulnerabilityType.XSS,
            severity=SeverityLevel.MEDIUM,
            file_path="template.html",
            line_number=5,
            code_snippet="{{ user_input }}",
            description="Test",
            confidence=0.7,
            deterministic_tool_confirmed=False,
            agent_id="test-agent",
            blueprint_id="test-bp",
            finding_fingerprint="vwx234",
        )
        assert finding.confidence == 0.7

    def test_validate_confidence_above_0_7_allowed_when_confirmed(self):
        """confidence > 0.7 should be allowed when deterministic_tool_confirmed=True."""
        finding = FindingOutput(
            vulnerability_type=VulnerabilityType.SQL_INJECTION,
            severity=SeverityLevel.CRITICAL,
            file_path="db.py",
            line_number=30,
            code_snippet="execute(query)",
            description="Test",
            confidence=0.95,
            deterministic_tool_confirmed=True,
            agent_id="test-agent",
            blueprint_id="test-bp",
            finding_fingerprint="yza567",
        )
        assert finding.confidence == 0.95

    def test_validate_calibrated_confidence_out_of_bounds_raises(self):
        """calibrated_confidence outside [0.0, 1.0] should raise."""
        with pytest.raises(ValueError, match="Input should be less than or equal to 1"):
            FindingOutput(
                vulnerability_type=VulnerabilityType.OTHER,
                severity=SeverityLevel.LOW,
                file_path="test.py",
                line_number=1,
                code_snippet="x = 1",
                description="Test",
                confidence=0.5,
                calibrated_confidence=1.5,
                agent_id="test-agent",
                blueprint_id="test-bp",
                finding_fingerprint="bcd890",
            )

    def test_validation_required_property_true_when_not_confirmed(self):
        """validation_required should be True when deterministic_tool_confirmed=False."""
        finding = FindingOutput(
            vulnerability_type=VulnerabilityType.INSECURE_DESERIALIZATION,
            severity=SeverityLevel.HIGH,
            file_path="pickle_usage.py",
            line_number=10,
            code_snippet="pickle.loads(data)",
            description="Test",
            confidence=0.6,
            deterministic_tool_confirmed=False,
            agent_id="test-agent",
            blueprint_id="test-bp",
            finding_fingerprint="efg123",
        )
        assert finding.validation_required is True

    def test_validation_required_property_false_when_confirmed(self):
        """validation_required should be False when deterministic_tool_confirmed=True."""
        finding = FindingOutput(
            vulnerability_type=VulnerabilityType.HARDCODED_SECRETS,
            severity=SeverityLevel.CRITICAL,
            file_path="secrets.py",
            line_number=2,
            code_snippet="API_KEY = 'xyz'",
            description="Test",
            confidence=0.95,
            deterministic_tool_confirmed=True,
            agent_id="test-agent",
            blueprint_id="test-bp",
            finding_fingerprint="hij456",
        )
        assert finding.validation_required is False

    def test_finding_output_repr(self):
        """FindingOutput.__repr__ should show key info."""
        finding = FindingOutput(
            id=uuid4(),
            vulnerability_type=VulnerabilityType.OPEN_REDIRECT,
            severity=SeverityLevel.MEDIUM,
            file_path="redirect.py",
            line_number=15,
            code_snippet="redirect(url)",
            description="Test",
            confidence=0.6,
            agent_id="agent-1",
            blueprint_id="bp-1",
            finding_fingerprint="klm789",
            deterministic_tool_confirmed=False,
        )
        repr_str = repr(finding)
        assert "FindingOutput" in repr_str
        # Repr uses enum values (lowercase) rather than names.
        assert "open_redirect" in repr_str
        assert "medium" in repr_str
        assert "redirect.py:15" in repr_str


class TestCrossValidationResult:
    """Tests for CrossValidationResult validators."""

    def test_different_providers_required(self):
        """Same model provider should raise ValueError."""
        with pytest.raises(ValueError, match="Cross-validation requires different model providers"):
            CrossValidationResult(
                finding_id=uuid4(),
                primary_agent="agent-1",
                primary_model_provider="anthropic",
                validation_agent="agent-2",
                validator_model_provider="anthropic",  # Same as primary
                primary_found=True,
                validator_found=True,
                consensus=ConsensusLevel.CONFIRMED,
                confidence_adjustment=0.1,
            )

    def test_different_providers_succeeds(self):
        """Different providers should succeed."""
        result = CrossValidationResult(
            finding_id=uuid4(),
            primary_agent="agent-1",
            primary_model_provider="anthropic",
            validation_agent="agent-2",
            validator_model_provider="openai",
            primary_found=True,
            validator_found=True,
            consensus=ConsensusLevel.CONFIRMED,
            confidence_adjustment=0.1,
        )
        assert result.isolation_verified is True

    def test_agreement_level_true_when_both_found(self):
        """agreement_level should be True when both agents find."""
        result = CrossValidationResult(
            finding_id=uuid4(),
            primary_agent="agent-1",
            primary_model_provider="anthropic",
            validation_agent="agent-2",
            validator_model_provider="openai",
            primary_found=True,
            validator_found=True,
            consensus=ConsensusLevel.CONFIRMED,
            confidence_adjustment=0.1,
        )
        assert result.agreement_level is True

    def test_agreement_level_true_when_neither_found(self):
        """agreement_level should be True when neither agent finds."""
        result = CrossValidationResult(
            finding_id=uuid4(),
            primary_agent="agent-1",
            primary_model_provider="anthropic",
            validation_agent="agent-2",
            validator_model_provider="openai",
            primary_found=False,
            validator_found=False,
            consensus=ConsensusLevel.CONFIRMED,
            confidence_adjustment=0.0,
        )
        assert result.agreement_level is True

    def test_agreement_level_false_when_disagree(self):
        """agreement_level should be False when agents disagree."""
        result = CrossValidationResult(
            finding_id=uuid4(),
            primary_agent="agent-1",
            primary_model_provider="anthropic",
            validation_agent="agent-2",
            validator_model_provider="openai",
            primary_found=True,
            validator_found=False,
            consensus=ConsensusLevel.DISPUTED,
            confidence_adjustment=-0.2,
        )
        assert result.agreement_level is False

    def test_cross_validation_result_repr(self):
        """CrossValidationResult.__repr__ should show finding_id and consensus."""
        finding_id = uuid4()
        result = CrossValidationResult(
            finding_id=finding_id,
            primary_agent="agent-1",
            primary_model_provider="anthropic",
            validation_agent="agent-2",
            validator_model_provider="openai",
            primary_found=True,
            validator_found=True,
            consensus=ConsensusLevel.CONFIRMED,
            confidence_adjustment=0.15,
        )
        repr_str = repr(result)
        assert "CrossValidationResult" in repr_str
        # Repr uses enum value (lowercase) rather than "ConsensusLevel.CONFIRMED".
        assert "confirmed" in repr_str


class TestSandboxExecutionResult:
    """Tests for SandboxExecutionResult timeout/error validation."""

    def test_timeout_not_failure_validator(self):
        """Timeout with large negative adjustment should raise."""
        with pytest.raises(ValueError, match="Timeout outcomes must not receive large negative"):
            SandboxExecutionResult(
                finding_id=uuid4(),
                outcome=ExecutionOutcome.TIMEOUT,
                execution_duration_ms=30000,
                timeout_limit_ms=30000,
                confidence_adjustment=-0.2,
            )

    def test_timeout_with_zero_adjustment_allowed(self):
        """Timeout with zero adjustment should succeed."""
        result = SandboxExecutionResult(
            finding_id=uuid4(),
            outcome=ExecutionOutcome.TIMEOUT,
            execution_duration_ms=30000,
            timeout_limit_ms=30000,
            confidence_adjustment=0.0,
        )
        assert result.confidence_adjustment == 0.0

    def test_timeout_with_small_negative_adjustment_allowed(self):
        """Timeout with small negative adjustment should succeed."""
        result = SandboxExecutionResult(
            finding_id=uuid4(),
            outcome=ExecutionOutcome.TIMEOUT,
            execution_duration_ms=30000,
            timeout_limit_ms=30000,
            confidence_adjustment=-0.05,
        )
        assert result.confidence_adjustment == -0.05

    def test_sandbox_error_with_nonzero_adjustment_raises(self):
        """Sandbox infrastructure error with nonzero adjustment should raise."""
        with pytest.raises(ValueError, match="Sandbox infrastructure errors must not adjust confidence"):
            SandboxExecutionResult(
                finding_id=uuid4(),
                outcome=ExecutionOutcome.SANDBOX_ERROR,
                execution_duration_ms=1000,
                confidence_adjustment=0.1,
            )

    def test_sandbox_error_with_zero_adjustment_succeeds(self):
        """Sandbox error with zero adjustment should succeed."""
        result = SandboxExecutionResult(
            finding_id=uuid4(),
            outcome=ExecutionOutcome.SANDBOX_ERROR,
            execution_duration_ms=500,
            confidence_adjustment=0.0,
        )
        assert result.outcome == ExecutionOutcome.SANDBOX_ERROR
        assert result.confidence_adjustment == 0.0


class TestSemanticValidationResult:
    """Tests for SemanticValidationResult code existence checks."""

    def test_code_not_exists_high_confidence_raises(self):
        """Code non-existent but high confidence should raise."""
        with pytest.raises(ValueError, match="Semantic confidence cannot exceed 0.3"):
            SemanticValidationResult(
                finding_id=uuid4(),
                code_exists_at_location=False,
                code_similarity_score=0.0,
                vulnerability_pattern_match=False,
                semantic_confidence=0.5,
            )

    def test_code_not_exists_low_confidence_allowed(self):
        """Code non-existent with low confidence should succeed."""
        result = SemanticValidationResult(
            finding_id=uuid4(),
            code_exists_at_location=False,
            code_similarity_score=0.0,
            vulnerability_pattern_match=False,
            semantic_confidence=0.2,
        )
        assert result.code_exists_at_location is False

    def test_code_similarity_low_high_confidence_raises(self):
        """Low code similarity but high confidence should raise."""
        with pytest.raises(ValueError, match="Semantic confidence cannot exceed 0.5"):
            SemanticValidationResult(
                finding_id=uuid4(),
                code_exists_at_location=True,
                code_similarity_score=0.3,
                vulnerability_pattern_match=True,
                semantic_confidence=0.8,
            )

    def test_code_similarity_low_medium_confidence_allowed(self):
        """Low similarity with medium confidence should succeed."""
        result = SemanticValidationResult(
            finding_id=uuid4(),
            code_exists_at_location=True,
            code_similarity_score=0.4,
            vulnerability_pattern_match=True,
            semantic_confidence=0.5,
        )
        assert result.code_similarity_score == 0.4

    def test_code_exists_high_similarity_high_confidence_allowed(self):
        """Code exists with high similarity and high confidence should succeed."""
        result = SemanticValidationResult(
            finding_id=uuid4(),
            code_exists_at_location=True,
            code_similarity_score=0.95,
            vulnerability_pattern_match=True,
            semantic_confidence=0.9,
        )
        assert result.semantic_confidence == 0.9


class TestCalibrationMetric:
    """Tests for CalibrationMetric accuracy validation."""

    def test_actual_accuracy_must_match_calculation(self):
        """actual_accuracy must equal true_positives / total_findings."""
        with pytest.raises(ValueError, match="actual_accuracy must equal true_positives"):
            CalibrationMetric(
                confidence_band="0.8-0.9",
                total_findings=100,
                true_positives=80,
                false_positives=20,
                actual_accuracy=0.70,  # Should be 0.80
                calibration_error=0.0,
            )

    def test_actual_accuracy_correct_calculation(self):
        """actual_accuracy correctly calculated."""
        metric = CalibrationMetric(
            confidence_band="0.8-0.9",
            total_findings=100,
            true_positives=85,
            false_positives=15,
            actual_accuracy=0.85,
            calibration_error=-0.05,
        )
        assert metric.actual_accuracy == 0.85

    def test_calibration_metric_repr(self):
        """CalibrationMetric.__repr__ shows band, accuracy, and error."""
        metric = CalibrationMetric(
            confidence_band="0.8-0.9",
            total_findings=200,
            true_positives=180,
            false_positives=20,
            actual_accuracy=0.90,
            calibration_error=0.10,
        )
        repr_str = repr(metric)
        assert "CalibrationMetric" in repr_str
        assert "0.8-0.9" in repr_str
        assert "90.00%" in repr_str
        assert "+10.00%" in repr_str


class TestPromptRegressionTest:
    """Tests for PromptRegressionTest status representation."""

    def test_prompt_regression_test_repr_pending(self):
        """__repr__ should show PENDING when last_passed is None."""
        test = PromptRegressionTest(
            template_id="prompt-v1",
            test_input="test code here",
            should_find=True,
            last_passed=None,
        )
        repr_str = repr(test)
        assert "PromptRegressionTest" in repr_str
        assert "PENDING" in repr_str
        assert "prompt-v1" in repr_str

    def test_prompt_regression_test_repr_pass(self):
        """__repr__ should show PASS when last_passed is True."""
        test = PromptRegressionTest(
            template_id="prompt-v2",
            test_input="test input",
            should_find=False,
            last_passed=True,
        )
        repr_str = repr(test)
        assert "PASS" in repr_str

    def test_prompt_regression_test_repr_fail(self):
        """__repr__ should show FAIL when last_passed is False."""
        test = PromptRegressionTest(
            template_id="prompt-v3",
            test_input="input",
            should_find=True,
            last_passed=False,
        )
        repr_str = repr(test)
        assert "FAIL" in repr_str


class TestDriftScore:
    """Tests for DriftScore drift detection validation."""

    def test_drift_detected_consistent_with_threshold(self):
        """drift_detected must be consistent with similarity vs threshold."""
        with pytest.raises(ValueError, match="drift_detected must be"):
            DriftScore(
                template_id="template-1",
                baseline_hash="a" * 64,
                current_hash="b" * 64,
                semantic_similarity=0.98,
                drift_detected=True,  # False because 0.98 >= 0.95 threshold
                threshold=0.95,
            )

    def test_drift_detected_true_below_threshold(self):
        """drift_detected should be True when similarity < threshold."""
        score = DriftScore(
            template_id="template-1",
            baseline_hash="a" * 64,
            current_hash="b" * 64,
            semantic_similarity=0.90,
            drift_detected=True,
            threshold=0.95,
        )
        assert score.drift_detected is True

    def test_drift_detected_false_at_threshold(self):
        """drift_detected should be False when similarity >= threshold."""
        score = DriftScore(
            template_id="template-1",
            baseline_hash="a" * 64,
            current_hash="b" * 64,
            semantic_similarity=0.95,
            drift_detected=False,
            threshold=0.95,
        )
        assert score.drift_detected is False

    def test_hash_format_validation_invalid_hex(self):
        """Invalid hex in hash should raise ValueError."""
        with pytest.raises(ValueError, match="Hash must be valid hexadecimal"):
            DriftScore(
                template_id="template-1",
                baseline_hash="Z" * 64,  # Z is not valid hex
                current_hash="a" * 64,
                semantic_similarity=0.95,
                drift_detected=False,
            )

    def test_hash_format_validation_valid_hex(self):
        """Valid hex hash should succeed."""
        score = DriftScore(
            template_id="template-1",
            baseline_hash="abcdef0123456789" * 4,
            current_hash="fedcba9876543210" * 4,
            semantic_similarity=0.85,
            drift_detected=True,
        )
        assert len(score.baseline_hash) == 64

    def test_drift_score_repr(self):
        """DriftScore.__repr__ shows template_id, similarity, and status."""
        score = DriftScore(
            template_id="template-v1",
            baseline_hash="a" * 64,
            current_hash="b" * 64,
            semantic_similarity=0.92,
            drift_detected=True,
        )
        repr_str = repr(score)
        assert "DriftScore" in repr_str
        assert "template-v1" in repr_str
        assert "0.920" in repr_str
        assert "DRIFT" in repr_str

    def test_drift_score_repr_stable(self):
        """DriftScore.__repr__ shows STABLE when no drift."""
        score = DriftScore(
            template_id="template-v2",
            baseline_hash="c" * 64,
            current_hash="d" * 64,
            semantic_similarity=0.97,
            drift_detected=False,
        )
        repr_str = repr(score)
        assert "STABLE" in repr_str


class TestFindingBatch:
    """Tests for FindingBatch computed properties."""

    def test_critical_count_property(self):
        """critical_count should count critical severity findings."""
        findings = [
            FindingOutput(
                vulnerability_type=VulnerabilityType.SQL_INJECTION,
                severity=SeverityLevel.CRITICAL,
                file_path="app.py",
                line_number=1,
                code_snippet="bad",
                description="Test",
                confidence=0.9,
                deterministic_tool_confirmed=True,
                agent_id="agent-1",
                blueprint_id="bp-1",
                finding_fingerprint="f1",
            ),
            FindingOutput(
                vulnerability_type=VulnerabilityType.XSS,
                severity=SeverityLevel.HIGH,
                file_path="app.js",
                line_number=2,
                code_snippet="bad",
                description="Test",
                confidence=0.7,
                agent_id="agent-1",
                blueprint_id="bp-1",
                finding_fingerprint="f2",
            ),
            FindingOutput(
                vulnerability_type=VulnerabilityType.HARDCODED_SECRETS,
                severity=SeverityLevel.CRITICAL,
                file_path="config.py",
                line_number=3,
                code_snippet="bad",
                description="Test",
                confidence=0.7,
                agent_id="agent-1",
                blueprint_id="bp-1",
                finding_fingerprint="f3",
            ),
        ]
        batch = FindingBatch(
            blueprint_id="bp-1",
            findings=findings,
            agent_id="agent-1",
            total_files_scanned=5,
            execution_duration_seconds=2.5,
        )
        assert batch.critical_count == 2

    def test_unconfirmed_count_property(self):
        """unconfirmed_count should count findings not confirmed by tools."""
        findings = [
            FindingOutput(
                vulnerability_type=VulnerabilityType.SQL_INJECTION,
                severity=SeverityLevel.HIGH,
                file_path="app.py",
                line_number=1,
                code_snippet="bad",
                description="Test",
                confidence=0.9,
                deterministic_tool_confirmed=True,
                agent_id="agent-1",
                blueprint_id="bp-1",
                finding_fingerprint="f1",
            ),
            FindingOutput(
                vulnerability_type=VulnerabilityType.XSS,
                severity=SeverityLevel.MEDIUM,
                file_path="app.js",
                line_number=2,
                code_snippet="bad",
                description="Test",
                confidence=0.7,
                deterministic_tool_confirmed=False,
                agent_id="agent-1",
                blueprint_id="bp-1",
                finding_fingerprint="f2",
            ),
            FindingOutput(
                vulnerability_type=VulnerabilityType.HARDCODED_SECRETS,
                severity=SeverityLevel.HIGH,
                file_path="config.py",
                line_number=3,
                code_snippet="bad",
                description="Test",
                confidence=0.7,
                deterministic_tool_confirmed=False,
                agent_id="agent-1",
                blueprint_id="bp-1",
                finding_fingerprint="f3",
            ),
        ]
        batch = FindingBatch(
            blueprint_id="bp-1",
            findings=findings,
            agent_id="agent-1",
            total_files_scanned=5,
            execution_duration_seconds=2.5,
        )
        assert batch.unconfirmed_count == 2

    def test_finding_batch_repr(self):
        """FindingBatch.__repr__ shows blueprint_id, findings count, and critical count."""
        findings = [
            FindingOutput(
                vulnerability_type=VulnerabilityType.SQL_INJECTION,
                severity=SeverityLevel.CRITICAL,
                file_path="app.py",
                line_number=1,
                code_snippet="bad",
                description="Test",
                confidence=0.9,
                deterministic_tool_confirmed=True,
                agent_id="agent-1",
                blueprint_id="bp-1",
                finding_fingerprint="f1",
            ),
        ]
        batch = FindingBatch(
            blueprint_id="bp-1",
            findings=findings,
            agent_id="agent-1",
            total_files_scanned=3,
            execution_duration_seconds=1.5,
        )
        repr_str = repr(batch)
        assert "FindingBatch" in repr_str
        assert "bp-1" in repr_str
        assert "findings=1" in repr_str
        assert "critical=1" in repr_str
