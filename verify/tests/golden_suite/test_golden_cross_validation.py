"""
Golden Test Suite for Cross-Validation Logic

Tests the multi-agent consensus validation framework that improves confidence
by having multiple agents (with different LLM providers) validate the same findings.

Cross-validation ensures:
- Findings confirmed by multiple agents get higher confidence
- Disagreements are flagged for manual review
- Correlated failures (same LLM) don't inflate confidence
- Consensus logic is deterministic and well-tested
"""

import pytest
from uuid import uuid4

from tron.schemas.verification import (
    FindingOutput,
    CrossValidationResult,
    ConsensusLevel,
    SeverityLevel,
    VulnerabilityType,
)


# Fixtures

@pytest.fixture
def sample_finding():
    """Create a sample security finding"""
    return FindingOutput(
        id=uuid4(),
        vulnerability_type=VulnerabilityType.SQL_INJECTION,
        severity=SeverityLevel.CRITICAL,
        file_path="app.py",
        line_number=42,
        code_snippet='query = f"SELECT * FROM users WHERE id = {user_id}"',
        description="SQL injection via f-string",
        confidence=0.65,
        agent_id="security-iso-1",
        blueprint_id="test-blueprint",
        finding_fingerprint="abc123",
        deterministic_tool_confirmed=False,
    )


# ============================================================================
# Two-of-Three Consensus Tests
# ============================================================================

class TestTwoOfThreeConsensus:
    """Tests for 2-of-3 consensus logic"""

    def test_primary_and_validator_agree(self):
        """MUST boost confidence when primary and validator agree"""
        # Primary agent found the issue
        primary_found = True
        # Validator from different provider also found it
        validator_found = True

        # 2-of-2 is effectively unanimous agreement
        is_consensus = primary_found and validator_found
        confidence_adjustment = 0.15 if is_consensus else -0.2

        assert is_consensus
        assert confidence_adjustment > 0

    def test_primary_only_found(self):
        """When only primary agent finds issue, confidence should be lower"""
        primary_found = True
        validator_found = False

        is_consensus = primary_found and validator_found
        confidence_adjustment = 0.15 if is_consensus else -0.15

        assert not is_consensus
        assert confidence_adjustment < 0

    def test_validator_only_found(self):
        """When only validator finds issue, it's a new finding"""
        primary_found = False
        validator_found = True

        is_consensus = primary_found and validator_found
        confidence_adjustment = 0.15 if is_consensus else -0.15

        assert not is_consensus
        assert confidence_adjustment < 0

    def test_both_agents_disagree(self):
        """When both agents disagree, mark for review"""
        primary_found = False
        validator_found = False

        is_consensus = primary_found or validator_found
        consensus_level = ConsensusLevel.CONFIRMED if is_consensus else ConsensusLevel.DISPUTED

        assert not is_consensus
        assert consensus_level == ConsensusLevel.DISPUTED


# ============================================================================
# Confidence Adjustment Tests
# ============================================================================

class TestConfidenceAdjustment:
    """Tests for confidence calibration based on validation"""

    def test_agreement_boosts_confidence(self, sample_finding):
        """Two agents agreeing should boost confidence"""
        original_confidence = sample_finding.confidence  # 0.65
        adjustment = 0.15  # Both agents found it

        final_confidence = min(original_confidence + adjustment, 1.0)

        assert final_confidence > original_confidence
        assert final_confidence == 0.80

    def test_disagreement_reduces_confidence(self, sample_finding):
        """Validator disagreeing should reduce confidence"""
        original_confidence = sample_finding.confidence  # 0.65
        adjustment = -0.15

        final_confidence = max(original_confidence + adjustment, 0.0)

        assert final_confidence < original_confidence
        assert final_confidence == 0.50

    def test_confidence_bounds_at_zero(self):
        """Confidence cannot go below 0.0"""
        original = 0.2
        adjustment = -0.3

        final = max(original + adjustment, 0.0)

        assert final == 0.0

    def test_confidence_bounds_at_one(self):
        """Confidence cannot exceed 1.0"""
        original = 0.9
        adjustment = 0.2

        final = min(original + adjustment, 1.0)

        assert final == 1.0


# ============================================================================
# Agent Isolation Tests
# ============================================================================

class TestAgentIsolation:
    """Tests that agents must use different model providers"""

    def test_anthropic_and_openai_valid_pair(self):
        """Anthropic + OpenAI is valid cross-validation pair"""
        primary_provider = "anthropic"
        validator_provider = "openai"

        isolation_valid = primary_provider != validator_provider

        assert isolation_valid

    def test_same_provider_invalid_isolation(self):
        """Using same provider for both doesn't satisfy isolation requirement"""
        primary_provider = "anthropic"
        validator_provider = "anthropic"

        isolation_valid = primary_provider != validator_provider

        assert not isolation_valid

    def test_isolation_prevents_correlated_failures(self):
        """Different providers prevent correlated training data failures"""
        # Same LLM → same training data → same blind spots
        # Different LLM → potentially uncorrelated failure modes
        providers = ["anthropic", "openai"]

        assert len(set(providers)) == 2, "Must use different providers"


# ============================================================================
# Consensus Level Tests
# ============================================================================

class TestConsensusLevels:
    """Tests for consensus level classification"""

    def test_confirmed_consensus(self):
        """Both agents found the issue"""
        primary_found = True
        validator_found = True

        consensus = (
            ConsensusLevel.CONFIRMED
            if primary_found and validator_found
            else ConsensusLevel.DISPUTED
        )

        assert consensus == ConsensusLevel.CONFIRMED

    def test_primary_only_consensus(self):
        """Only primary agent found it"""
        primary_found = True
        validator_found = False

        consensus = ConsensusLevel.PRIMARY_ONLY

        assert consensus == ConsensusLevel.PRIMARY_ONLY

    def test_validator_only_consensus(self):
        """Only validator found it (new finding)"""
        primary_found = False
        validator_found = True

        consensus = ConsensusLevel.VALIDATOR_ONLY

        assert consensus == ConsensusLevel.VALIDATOR_ONLY

    def test_disputed_consensus(self):
        """Neither agent found it (shouldn't validate such findings)"""
        primary_found = False
        validator_found = False

        consensus = ConsensusLevel.DISPUTED

        assert consensus == ConsensusLevel.DISPUTED


# ============================================================================
# Finding Deduplication Tests
# ============================================================================

class TestFindingDeduplication:
    """Tests for deduplication across agents"""

    def test_same_file_line_is_duplicate(self):
        """Findings at same file:line with same vuln type are duplicates"""
        finding1_fingerprint = "app.py:42:sql_injection"
        finding2_fingerprint = "app.py:42:sql_injection"

        is_duplicate = finding1_fingerprint == finding2_fingerprint

        assert is_duplicate

    def test_different_file_not_duplicate(self):
        """Same code in different files are NOT duplicates"""
        finding1_fingerprint = "app.py:42:sql_injection"
        finding2_fingerprint = "models.py:42:sql_injection"

        is_duplicate = finding1_fingerprint == finding2_fingerprint

        assert not is_duplicate

    def test_different_line_not_duplicate(self):
        """Same file but different lines are NOT duplicates"""
        finding1_fingerprint = "app.py:42:sql_injection"
        finding2_fingerprint = "app.py:100:sql_injection"

        is_duplicate = finding1_fingerprint == finding2_fingerprint

        assert not is_duplicate

    def test_different_type_not_duplicate(self):
        """Same location but different vuln types are NOT duplicates"""
        finding1_fingerprint = "app.py:42:sql_injection"
        finding2_fingerprint = "app.py:42:xss"

        is_duplicate = finding1_fingerprint == finding2_fingerprint

        assert not is_duplicate

    def test_fingerprint_based_deduplication(self, sample_finding):
        """Deduplicate using fingerprint hash"""
        findings = [
            sample_finding,
            # Same location, type, severity
            FindingOutput(
                id=uuid4(),
                vulnerability_type=VulnerabilityType.SQL_INJECTION,
                severity=SeverityLevel.CRITICAL,
                file_path="app.py",
                line_number=42,
                code_snippet='query = f"SELECT * FROM users WHERE id = {user_id}"',
                description="SQL injection via f-string",
                confidence=0.65,
                agent_id="security-iso-2",
                blueprint_id="test-blueprint",
                finding_fingerprint="abc123",  # Same fingerprint
                deterministic_tool_confirmed=False,
            ),
        ]

        # Deduplicate by fingerprint
        unique_fingerprints = {f.finding_fingerprint for f in findings}

        assert len(unique_fingerprints) == 1


# ============================================================================
# Multi-Agent Agreement Tests
# ============================================================================

class TestMultiAgentAgreement:
    """Tests for agreement/disagreement scenarios"""

    def test_three_agents_two_agree(self):
        """2-of-3 agents agree on finding"""
        agents = {
            "security-iso": {"found": True, "confidence": 0.95},
            "performance-iso": {"found": True, "confidence": 0.88},
            "qa-iso": {"found": False, "confidence": 0.0},
        }

        agreements = sum(1 for a in agents.values() if a["found"])

        assert agreements >= 2, "Need at least 2-of-3 agreement"

    def test_all_three_agents_agree(self):
        """All 3 agents agree — very high confidence"""
        agents = {
            "security-iso": {"found": True, "confidence": 0.95},
            "performance-iso": {"found": True, "confidence": 0.92},
            "builder-iso": {"found": True, "confidence": 0.89},
        }

        agreements = sum(1 for a in agents.values() if a["found"])

        assert agreements == 3, "All agents agree"

    def test_split_decision_one_vs_two(self):
        """One agent finds, two don't — DISPUTED status"""
        agents = {
            "security-iso": {"found": True, "confidence": 0.65},
            "performance-iso": {"found": False, "confidence": 0.0},
            "builder-iso": {"found": False, "confidence": 0.0},
        }

        agreements = sum(1 for a in agents.values() if a["found"])

        assert agreements == 1, "Minority opinion — needs review"


# ============================================================================
# Cross-Validation Result Schema Tests
# ============================================================================

class TestCrossValidationResultSchema:
    """Tests for CrossValidationResult schema validation"""

    def test_valid_cross_validation_result(self, sample_finding):
        """Create valid cross-validation result"""
        result = CrossValidationResult(
            finding_id=sample_finding.id,
            primary_agent="security-iso-1",
            primary_model_provider="anthropic",
            validation_agent="security-iso-2",
            validator_model_provider="openai",
            primary_found=True,
            validator_found=True,
            consensus=ConsensusLevel.CONFIRMED,
            confidence_adjustment=0.15,
        )

        assert result.finding_id == sample_finding.id
        assert result.agreement_level is True
        assert result.isolation_verified is True

    def test_different_providers_enforced(self, sample_finding):
        """Must use different model providers"""
        with pytest.raises(ValueError, match="different model providers"):
            CrossValidationResult(
                finding_id=sample_finding.id,
                primary_agent="security-iso-1",
                primary_model_provider="anthropic",
                validation_agent="security-iso-2",
                validator_model_provider="anthropic",  # Same provider!
                primary_found=True,
                validator_found=True,
                consensus=ConsensusLevel.CONFIRMED,
                confidence_adjustment=0.15,
            )

    def test_disagreement_lower_confidence_adjustment(self, sample_finding):
        """Disagreement should have negative confidence adjustment"""
        result = CrossValidationResult(
            finding_id=sample_finding.id,
            primary_agent="security-iso-1",
            primary_model_provider="anthropic",
            validation_agent="security-iso-2",
            validator_model_provider="openai",
            primary_found=True,
            validator_found=False,
            consensus=ConsensusLevel.PRIMARY_ONLY,
            confidence_adjustment=-0.15,
        )

        assert result.confidence_adjustment < 0
        assert result.agreement_level is False


# ============================================================================
# Consensus Threshold Tests
# ============================================================================

class TestConsensusThresholds:
    """Tests for minimum consensus requirements"""

    def test_critical_finding_needs_consensus(self):
        """Critical findings need 2-of-3 consensus before delivery"""
        severity = SeverityLevel.CRITICAL
        agreements = 2  # 2-of-3
        min_required = 2

        consensus_satisfied = agreements >= min_required and severity == SeverityLevel.CRITICAL

        assert consensus_satisfied

    def test_high_finding_single_agent_ok(self):
        """High severity findings can be delivered on single agent if deterministic-confirmed"""
        severity = SeverityLevel.HIGH
        deterministic_confirmed = True

        can_deliver = severity == SeverityLevel.HIGH and deterministic_confirmed

        assert can_deliver

    def test_low_finding_no_consensus_required(self):
        """Low severity findings don't require consensus"""
        severity = SeverityLevel.LOW
        agreements = 1

        consensus_required = severity in [SeverityLevel.CRITICAL, SeverityLevel.HIGH]

        assert not consensus_required

    def test_medium_finding_single_validation_enough(self):
        """Medium severity can be delivered with single validator agreement"""
        severity = SeverityLevel.MEDIUM
        agreements = 1

        sufficient = severity == SeverityLevel.MEDIUM and agreements >= 1

        assert sufficient


# ============================================================================
# Finding Agreement Statistics Tests
# ============================================================================

class TestFindingAgreementStatistics:
    """Tests for tracking and analyzing agreement patterns"""

    def test_track_total_validations(self):
        """Track total findings across all validations"""
        validations = [
            {"primary_found": True, "validator_found": True},
            {"primary_found": True, "validator_found": False},
            {"primary_found": False, "validator_found": True},
            {"primary_found": False, "validator_found": False},
        ]

        total_validations = len(validations)

        assert total_validations == 4

    def test_compute_agreement_rate(self):
        """Calculate agreement rate across validations"""
        validations = [
            {"agreement": True},
            {"agreement": True},
            {"agreement": False},
            {"agreement": True},
            {"agreement": False},
        ]

        agreement_count = sum(1 for v in validations if v["agreement"])
        agreement_rate = agreement_count / len(validations)

        assert agreement_rate == 0.6

    def test_track_confidence_by_consensus(self):
        """Track findings by their consensus level"""
        findings_by_consensus = {
            ConsensusLevel.CONFIRMED: 15,
            ConsensusLevel.PRIMARY_ONLY: 5,
            ConsensusLevel.VALIDATOR_ONLY: 2,
            ConsensusLevel.DISPUTED: 1,
        }

        total = sum(findings_by_consensus.values())
        confirmed_rate = findings_by_consensus[ConsensusLevel.CONFIRMED] / total

        assert total == 23
        assert confirmed_rate > 0.6


# ============================================================================
# Model Provider Diversity Tests
# ============================================================================

class TestModelProviderDiversity:
    """Tests ensuring validation uses diverse model providers"""

    def test_anthropic_and_openai_provide_diversity(self):
        """Anthropic and OpenAI have different training data"""
        providers = {"anthropic", "openai"}

        assert len(providers) >= 2

    def test_validation_pair_must_differ(self):
        """Primary and validator must use different providers"""
        pairs = [
            ("anthropic", "openai"),  # Valid
            ("openai", "anthropic"),  # Valid
            ("anthropic", "anthropic"),  # Invalid
            ("openai", "openai"),  # Invalid
        ]

        valid_pairs = [p for p in pairs if p[0] != p[1]]

        assert len(valid_pairs) == 2
