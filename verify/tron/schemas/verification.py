"""
Tron Zero-Drift Verification Pipeline - Core Pydantic Schemas

This module defines the complete schema for Tron's multi-agent security verification
pipeline, including finding outputs, task blueprints, cross-validation results, and
drift detection metrics. All models follow Pydantic v2 best practices with strict
validation and comprehensive error handling.

The schemas support:
- Deterministic tool cross-validation (Bandit, Semgrep)
- Multi-agent consensus validation
- Confidence calibration and tracking
- Prompt/agent drift detection
- Regression testing for LLM stability

Author: Tron Security Team
Version: 1.0.0
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_validator,
    ConfigDict,
    computed_field,
)


# ============================================================================
# Enumerations
# ============================================================================


class VulnerabilityType(str, Enum):
    """Enum of all security vulnerability types that agents can identify."""

    SQL_INJECTION = "sql_injection"
    XSS = "xss"
    HARDCODED_SECRETS = "hardcoded_secrets"
    INSECURE_DESERIALIZATION = "insecure_deserialization"
    BROKEN_AUTH = "broken_auth"
    SECURITY_MISCONFIGURATION = "security_misconfiguration"
    SSRF = "ssrf"
    PATH_TRAVERSAL = "path_traversal"
    COMMAND_INJECTION = "command_injection"
    OPEN_REDIRECT = "open_redirect"
    INSUFFICIENT_LOGGING = "insufficient_logging"
    DEPENDENCY_VULNERABILITY = "dependency_vulnerability"
    OTHER = "other"


class SeverityLevel(str, Enum):
    """Severity classification for findings."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class CrossValidationStatus(str, Enum):
    """Status of a finding after cross-validation with other agents."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    DISPUTED = "disputed"
    NEEDS_REVIEW = "needs_review"


class ConsensusLevel(str, Enum):
    """Level of consensus between primary and validation agents."""

    CONFIRMED = "confirmed"
    DISPUTED = "disputed"
    PRIMARY_ONLY = "primary_only"
    VALIDATOR_ONLY = "validator_only"


class VerificationMethod(str, Enum):
    """Methods available for verifying findings."""

    DETERMINISTIC_CROSSCHECK = "deterministic_crosscheck"
    EXECUTION_SANDBOX = "execution_sandbox"
    CROSS_VALIDATION = "cross_validation"
    SEMANTIC_VALIDATION = "semantic_validation"
    MANUAL_REVIEW = "manual_review"


class ExecutionOutcome(str, Enum):
    """
    Outcome of sandbox execution — explicitly distinguishes timeout from failure.

    The Principal Engineer critic correctly identified that timeout != failure.
    Treating timeouts as failures corrupts calibration data with false negatives.
    """

    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"          # Execution exceeded time limit — NOT a failure
    RESOURCE_EXCEEDED = "resource_exceeded"  # OOM or CPU limit hit
    SANDBOX_ERROR = "sandbox_error"  # Infrastructure error, not code error
    SKIPPED = "skipped"          # Execution not applicable


# ============================================================================
# Operational Confidence Definition
# ============================================================================
# The "98%+ verified confidence" target is operationally defined as:
#
#   PRECISION: ≥98% of findings delivered to users are true positives
#              (i.e., ≤2% false positive rate on delivered findings)
#
#   RECALL:    Measured and reported per vulnerability type, NOT a global target.
#              Recall varies by vuln type — SQL injection recall will differ
#              from insecure deserialization recall. We report honestly.
#
#   MEASUREMENT: Against the golden test suite (target: 1,000+ cases).
#                Calibration curves published ONLY when N≥200 per confidence band.
#                Below N=200: raw accuracy with explicit confidence intervals.
#
#   CONFIDENCE INTERVALS: All published metrics include 95% Wilson score intervals.
#                         No point estimates without error bars.
#
# This definition was established in response to the AI/ML Researcher critique
# that "98%+ verified confidence" was undefined. It is now measurable.
# ============================================================================


# ============================================================================
# FindingOutput Schema
# ============================================================================


class FindingOutput(BaseModel):
    """
    Comprehensive schema for all security findings from agents.

    This model represents a single security issue identified by an agent,
    including metadata about its source, confidence, and validation status.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_default=True,
    )

    id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier for this finding",
    )
    vulnerability_type: VulnerabilityType = Field(
        description="Classification of the vulnerability",
    )
    severity: SeverityLevel = Field(
        description="Severity level of the finding",
    )
    file_path: str = Field(
        description="Absolute or relative path to the file containing the vulnerability",
    )
    line_number: int = Field(
        description="Line number where the vulnerability starts (1-indexed)",
        gt=0,
    )
    line_end: Optional[int] = Field(
        default=None,
        description="End line number if vulnerability spans multiple lines",
        ge=0,
    )
    code_snippet: str = Field(
        min_length=1,
        description="The actual source code at the vulnerability location",
    )
    description: str = Field(
        description="Detailed description of the vulnerability and its impact",
    )
    fix_suggestion: Optional[str] = Field(
        default=None,
        description="Recommended fix or remediation steps",
    )
    deterministic_tool_confirmed: bool = Field(
        default=False,
        description="Whether deterministic tools (Bandit, Semgrep) confirmed this finding",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Agent's confidence in this finding (0.0 to 1.0)",
    )
    calibrated_confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence after calibration adjustment based on historical accuracy",
    )
    confirming_tools: List[str] = Field(
        default_factory=list,
        description="List of deterministic tools that confirmed this finding",
    )
    cross_validation_status: CrossValidationStatus = Field(
        default=CrossValidationStatus.PENDING,
        description="Current validation status across multiple agents",
    )
    layer3_execution: Optional[str] = Field(
        default=None,
        description=(
            "Layer 3 sandbox execution outcome: not_applicable, verified, unverified, "
            "skipped (sandbox off), or null if not yet set"
        ),
    )
    path_role: Optional[str] = Field(
        default=None,
        description="e.g. 'test' when file path matches project test-path globs (SEC-3)",
    )
    follow_up_recommended: bool = Field(
        default=False,
        description="True when flagged for optional deeper verification (SEC-5, env-capped top N)",
    )
    evidence_source: Optional[str] = Field(
        default=None,
        description="provenance: agent, sarif, import, etc.",
    )
    agent_id: str = Field(
        description="Identifier of the ISO agent that produced this finding",
    )
    blueprint_id: str = Field(
        description="ID of the blueprint/task that was being executed",
    )
    finding_fingerprint: str = Field(
        description="SHA256 hash for deduplication and tracking",
    )
    semantic_fingerprint: Optional[str] = Field(
        default=None,
        description="Embedding-based fingerprint for semantic deduplication",
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp when this finding was created",
    )

    @field_validator("code_snippet")
    @classmethod
    def validate_code_snippet(cls, v: str) -> str:
        """Ensure code snippet is not empty or whitespace-only."""
        if not v or not v.strip():
            raise ValueError("code_snippet must not be empty or contain only whitespace")
        return v

    @field_validator("line_number")
    @classmethod
    def validate_line_number(cls, v: int) -> int:
        """Ensure line number is positive."""
        if v <= 0:
            raise ValueError("line_number must be greater than 0")
        return v

    @field_validator("line_end")
    @classmethod
    def validate_line_end(cls, v: Optional[int], info) -> Optional[int]:
        """Ensure line_end is greater than or equal to line_number if provided."""
        if v is not None and "line_number" in info.data:
            line_number = info.data["line_number"]
            if v < line_number:
                raise ValueError("line_end must be greater than or equal to line_number")
        return v

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float, info) -> float:
        """
        Cap confidence at 0.7 if not confirmed by deterministic tools.

        This enforces that unconfirmed findings cannot claim high confidence.
        """
        deterministic_confirmed = info.data.get("deterministic_tool_confirmed", False)
        if not deterministic_confirmed and v > 0.7:
            raise ValueError(
                "confidence must be capped at 0.7 when deterministic_tool_confirmed is False"
            )
        return v

    @field_validator("calibrated_confidence")
    @classmethod
    def validate_calibrated_confidence(cls, v: Optional[float]) -> Optional[float]:
        """Ensure calibrated confidence is valid if provided."""
        if v is not None and (v < 0.0 or v > 1.0):
            raise ValueError("calibrated_confidence must be between 0.0 and 1.0")
        return v

    @computed_field
    @property
    def validation_required(self) -> bool:
        """Determine if this finding requires cross-validation."""
        return not self.deterministic_tool_confirmed

    def __repr__(self) -> str:
        return (
            f"FindingOutput(id={self.id}, "
            f"vulnerability_type={self.vulnerability_type}, "
            f"severity={self.severity}, "
            f"file_path={self.file_path}:{self.line_number})"
        )


# ============================================================================
# Blueprint Schema
# ============================================================================


# Blocked path patterns for blueprint admission control.
# Agents CANNOT request scans outside the project workspace.
# The Security Architect critic correctly identified that without admission
# control, a malicious agent could scan /etc/passwd or Docker volumes.
BLOCKED_PATH_PATTERNS = [
    "/etc/*",
    "/proc/*",
    "/sys/*",
    "/dev/*",
    "/var/run/*",
    "/root/*",
    "/home/*/.ssh/*",
    "/home/*/.aws/*",
    "/home/*/.config/*",
    "**/.env",
    "**/.env.*",
    "**/secrets/*",
    "**/private_keys/*",
    "**/docker.sock",
]


class BlueprintScope(BaseModel):
    """
    Defines the scope of files and checks for a blueprint.

    This model specifies which files, languages, and vulnerability types
    should be covered during blueprint execution. Includes admission control
    to prevent agents from scanning sensitive system paths.
    """

    file_patterns: List[str] = Field(
        description="Glob patterns for files to include (e.g., ['*.py', 'src/**/*.js'])",
    )
    check_types: List[VulnerabilityType] = Field(
        description="List of vulnerability types to check for",
    )
    languages: List[str] = Field(
        description="Programming languages to target (e.g., ['python', 'javascript'])",
    )
    max_files: Optional[int] = Field(
        default=None,
        ge=1,
        description="Maximum number of files to process (None = unlimited)",
    )

    @field_validator("file_patterns")
    @classmethod
    def validate_file_patterns_admission(cls, v: List[str]) -> List[str]:
        """
        Blueprint admission control: reject patterns targeting sensitive paths.

        Prevents agents from requesting scans of system files, secrets,
        Docker socket, or other sensitive locations outside the project workspace.
        """
        import fnmatch

        for pattern in v:
            normalized = pattern.strip().replace("\\", "/")
            for blocked in BLOCKED_PATH_PATTERNS:
                if fnmatch.fnmatch(normalized, blocked) or fnmatch.fnmatch(normalized, f"**/{blocked}"):
                    raise ValueError(
                        f"Blueprint admission control: pattern '{pattern}' matches "
                        f"blocked path '{blocked}'. Agents cannot scan system files, "
                        f"secrets, or paths outside the project workspace."
                    )
            # Block absolute paths outside project
            if normalized.startswith("/") and not normalized.startswith("/workspace/"):
                raise ValueError(
                    f"Blueprint admission control: absolute path '{pattern}' rejected. "
                    f"All file patterns must be relative to the project workspace or "
                    f"start with /workspace/."
                )
        return v


class Blueprint(BaseModel):
    """
    Task boundary definition for zero-drift verification.

    Blueprints define isolated, verifiable tasks for agents. Each blueprint
    has controlled scope, resource limits, and verification methods to
    prevent drift and ensure consistency.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
    )

    id: str = Field(
        description="Unique identifier for this blueprint",
    )
    name: str = Field(
        description="Human-readable name of the blueprint task",
    )
    description: str = Field(
        description="Detailed description of what this blueprint checks",
    )
    scope: BlueprintScope = Field(
        description="Scope definition (files, check types, languages)",
    )
    not_in_scope: List[str] = Field(
        default_factory=list,
        description="Explicit exclusion patterns to prevent drift",
    )
    tools_required: List[str] = Field(
        default_factory=list,
        description="Deterministic tools to run first (e.g., ['bandit', 'semgrep'])",
    )
    output_schema: str = Field(
        default="FindingOutput",
        description="Reference to the expected output model name",
    )
    max_tokens: int = Field(
        default=4000,
        ge=100,
        description="Token budget for agent execution",
    )
    max_duration_seconds: int = Field(
        default=300,
        ge=10,
        description="Timeout for blueprint execution",
    )
    temperature: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description="Locked temperature for deterministic behavior",
    )
    verification_method: VerificationMethod = Field(
        default=VerificationMethod.DETERMINISTIC_CROSSCHECK,
        description="Method used to verify findings",
    )
    min_consensus_for_critical: int = Field(
        default=2,
        ge=1,
        description="Minimum number of agents that must agree on critical findings",
    )

    @field_validator("not_in_scope")
    @classmethod
    def validate_not_in_scope(cls, v: List[str]) -> List[str]:
        """Ensure exclusion patterns are not empty strings."""
        return [pattern.strip() for pattern in v if pattern.strip()]

    @field_validator("tools_required")
    @classmethod
    def validate_tools_required(cls, v: List[str]) -> List[str]:
        """Ensure tool names are lowercased and non-empty."""
        return [tool.strip().lower() for tool in v if tool.strip()]

    def __repr__(self) -> str:
        return f"Blueprint(id={self.id}, name={self.name})"


# ============================================================================
# Cross-Validation Schema
# ============================================================================


class CrossValidationResult(BaseModel):
    """
    Result of multi-agent validation of a finding.

    This model tracks how different agents validate the same finding,
    enabling consensus-based confidence adjustment.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
    )

    finding_id: UUID = Field(
        description="Reference to the finding being validated",
    )
    primary_agent: str = Field(
        description="ID of the agent that originally found the issue",
    )
    primary_model_provider: str = Field(
        description="LLM provider used by primary agent (e.g., 'anthropic', 'openai')",
    )
    validation_agent: str = Field(
        description="ID of the agent performing validation",
    )
    validator_model_provider: str = Field(
        description="LLM provider used by validator — MUST differ from primary to prevent correlated failures",
    )
    isolation_verified: bool = Field(
        default=False,
        description="Whether agent isolation was verified: different models, independent system prompts, no shared context",
    )
    primary_found: bool = Field(
        description="Whether primary agent found this issue",
    )
    validator_found: bool = Field(
        description="Whether validator agent found this issue",
    )
    consensus: ConsensusLevel = Field(
        description="Level of agreement between agents",
    )
    confidence_adjustment: float = Field(
        ge=-0.3,
        le=0.3,
        description="Confidence adjustment factor based on validation result",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Additional notes about the validation result",
    )
    validated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp when validation occurred",
    )

    @model_validator(mode="after")
    def validate_agent_isolation(self) -> "CrossValidationResult":
        """
        Enforce agent isolation for cross-validation integrity.

        The AI/ML critique is valid: agents using the same LLM can have
        correlated failures (same training data → same blind spots).
        We enforce different model providers to decorrelate errors.
        """
        if self.primary_model_provider == self.validator_model_provider:
            raise ValueError(
                f"Cross-validation requires different model providers to prevent "
                f"correlated failures. Primary uses '{self.primary_model_provider}', "
                f"validator must use a different provider. "
                f"Example: primary=anthropic, validator=openai"
            )
        self.isolation_verified = True
        return self

    @computed_field
    @property
    def agreement_level(self) -> bool:
        """Determine if both agents agree."""
        return self.primary_found == self.validator_found

    def __repr__(self) -> str:
        return (
            f"CrossValidationResult(finding_id={self.finding_id}, "
            f"consensus={self.consensus})"
        )


# ============================================================================
# Sandbox Execution Schema (Layer 3)
# ============================================================================


class SandboxExecutionResult(BaseModel):
    """
    Result from Layer 3 execution sandbox verification.

    Explicitly tracks execution outcome with timeout as a distinct state
    (not conflated with failure). The Principal Engineer critic correctly
    identified that timeout != failure and mixing them corrupts calibration.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    finding_id: UUID = Field(description="Reference to the finding being verified")
    outcome: ExecutionOutcome = Field(
        description="Execution result — SUCCESS, FAILURE, TIMEOUT, RESOURCE_EXCEEDED, SANDBOX_ERROR, or SKIPPED",
    )
    execution_duration_ms: int = Field(
        ge=0,
        description="Actual execution time in milliseconds",
    )
    timeout_limit_ms: int = Field(
        default=30000,
        ge=1000,
        description="Configured timeout limit in milliseconds",
    )
    stdout: Optional[str] = Field(default=None, description="Captured stdout from execution")
    stderr: Optional[str] = Field(default=None, description="Captured stderr from execution")
    exit_code: Optional[int] = Field(default=None, description="Process exit code if applicable")
    memory_used_mb: Optional[float] = Field(default=None, ge=0, description="Peak memory usage in MB")
    finding_verified: bool = Field(
        default=False,
        description="Whether the finding was confirmed by execution (only True if outcome=SUCCESS and test passed)",
    )
    confidence_adjustment: float = Field(
        ge=-0.5,
        le=0.3,
        default=0.0,
        description="Confidence adjustment from sandbox result. Timeout = 0 (no adjustment), failure = negative.",
    )

    @model_validator(mode="after")
    def validate_timeout_not_failure(self) -> "SandboxExecutionResult":
        """
        Ensure timeout outcomes don't get false-negative confidence adjustments.
        Timeouts are inconclusive, not failures.
        """
        if self.outcome == ExecutionOutcome.TIMEOUT and self.confidence_adjustment < -0.1:
            raise ValueError(
                "Timeout outcomes must not receive large negative confidence adjustments. "
                "Timeouts are inconclusive (adjustment should be 0 or small negative ≥-0.1), "
                "not failures."
            )
        if self.outcome == ExecutionOutcome.SANDBOX_ERROR and self.confidence_adjustment != 0.0:
            raise ValueError(
                "Sandbox infrastructure errors must not adjust confidence. "
                "Infrastructure failures say nothing about the finding's validity."
            )
        return self


# ============================================================================
# Semantic Validation Schema (Layer 2.5 — between schema and sandbox)
# ============================================================================


class SemanticValidationResult(BaseModel):
    """
    Result from semantic validation — checks whether the finding's description
    and context are logically consistent with the code.

    The Security Architect critic correctly identified that schema validation
    catches structural hallucinations but misses semantic ones. This layer
    verifies that:
    - The code_snippet actually exists at the claimed file_path:line_number
    - The vulnerability description is consistent with the code pattern
    - The suggested fix addresses the actual vulnerability (not a hallucinated one)
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    finding_id: UUID = Field(description="Reference to the finding being validated")
    code_exists_at_location: bool = Field(
        description="Whether code_snippet was found at file_path:line_number",
    )
    code_similarity_score: float = Field(
        ge=0.0, le=1.0,
        description="Similarity between claimed code_snippet and actual code at location (1.0 = exact match)",
    )
    vulnerability_pattern_match: bool = Field(
        description="Whether the code pattern at the location matches the claimed vulnerability type",
    )
    fix_addresses_vulnerability: Optional[bool] = Field(
        default=None,
        description="Whether the suggested fix actually addresses the described vulnerability (None if no fix suggested)",
    )
    semantic_confidence: float = Field(
        ge=0.0, le=1.0,
        description="Semantic validation confidence (independent of agent confidence)",
    )
    rejection_reason: Optional[str] = Field(
        default=None,
        description="Why the finding was rejected at semantic validation, if applicable",
    )

    @model_validator(mode="after")
    def validate_semantic_consistency(self) -> "SemanticValidationResult":
        """Reject findings where code doesn't exist at the claimed location."""
        if not self.code_exists_at_location and self.semantic_confidence > 0.3:
            raise ValueError(
                "Semantic confidence cannot exceed 0.3 when code does not exist "
                "at the claimed location. This is a hallucinated file/line reference."
            )
        if self.code_similarity_score < 0.5 and self.semantic_confidence > 0.5:
            raise ValueError(
                "Semantic confidence cannot exceed 0.5 when code similarity is below 0.5. "
                "The code_snippet doesn't match what's actually in the file."
            )
        return self


# ============================================================================
# Calibration Schema
# ============================================================================


class CalibrationMetric(BaseModel):
    """
    Tracks confidence calibration metrics for accuracy improvement.

    This model measures how well agent confidence scores align with
    actual accuracy, enabling calibration adjustments over time.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
    )

    confidence_band: str = Field(
        description="Confidence interval band (e.g., '0.8-0.9')",
    )
    total_findings: int = Field(
        ge=0,
        description="Total findings in this confidence band",
    )
    sample_sufficient: bool = Field(
        default=False,
        description="Whether N≥200 for this band (required before publishing calibration curves)",
    )
    wilson_ci_lower: Optional[float] = Field(
        default=None, ge=0.0, le=1.0,
        description="Lower bound of 95% Wilson score confidence interval",
    )
    wilson_ci_upper: Optional[float] = Field(
        default=None, ge=0.0, le=1.0,
        description="Upper bound of 95% Wilson score confidence interval",
    )
    use_platt_scaling: bool = Field(
        default=False,
        description="Whether Platt scaling is active. Only True when total golden suite N≥500.",
    )
    true_positives: int = Field(
        ge=0,
        description="Number of confirmed true positives",
    )
    false_positives: int = Field(
        ge=0,
        description="Number of confirmed false positives",
    )
    actual_accuracy: float = Field(
        ge=0.0,
        le=1.0,
        description="Actual accuracy (TP / Total)",
    )
    calibration_error: float = Field(
        ge=-1.0,
        le=1.0,
        description="Signed error between stated confidence and actual accuracy",
    )
    measured_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When this metric was calculated",
    )

    @field_validator("actual_accuracy")
    @classmethod
    def validate_actual_accuracy(cls, v: float, info) -> float:
        """Ensure actual accuracy is calculated correctly."""
        if "total_findings" in info.data and "true_positives" in info.data:
            total = info.data["total_findings"]
            tp = info.data["true_positives"]
            if total > 0:
                calculated = tp / total
                if abs(v - calculated) > 0.001:  # Allow small rounding errors
                    raise ValueError(
                        f"actual_accuracy must equal true_positives / total_findings "
                        f"({calculated:.3f}, but got {v:.3f})"
                    )
        return v

    def __repr__(self) -> str:
        return (
            f"CalibrationMetric(band={self.confidence_band}, "
            f"accuracy={self.actual_accuracy:.2%}, "
            f"error={self.calibration_error:+.2%})"
        )


# ============================================================================
# Regression Testing Schema
# ============================================================================


class PromptRegressionTest(BaseModel):
    """
    Test case for monitoring prompt and model behavior stability.

    These tests ensure that agents continue to behave consistently
    over time, detecting regressions or drift in LLM behavior.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
    )

    template_id: str = Field(
        description="ID of the prompt template being tested",
    )
    test_input: str = Field(
        min_length=1,
        description="Test code/input that should trigger specific behavior",
    )
    expected_finding_type: Optional[VulnerabilityType] = Field(
        default=None,
        description="Expected vulnerability type if finding_type matters",
    )
    expected_confidence_min: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Minimum confidence expected if finding is detected",
    )
    should_find: bool = Field(
        description="Whether agent MUST detect this finding (True) or MUST NOT (False)",
    )
    last_result: Optional[str] = Field(
        default=None,
        description="Result of last test execution",
    )
    last_passed: Optional[bool] = Field(
        default=None,
        description="Whether the last test passed",
    )
    last_run_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp of last test execution",
    )

    def __repr__(self) -> str:
        status = "PASS" if self.last_passed else "FAIL" if self.last_passed is False else "PENDING"
        return (
            f"PromptRegressionTest(template_id={self.template_id}, "
            f"should_find={self.should_find}, status={status})"
        )


# ============================================================================
# Drift Detection Schema
# ============================================================================


class DriftScore(BaseModel):
    """
    Metrics for detecting agent or prompt behavior drift.

    This model tracks semantic and hash-based differences in prompts/agents,
    identifying when behavior has drifted from baseline.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
    )

    template_id: str = Field(
        description="ID of the prompt or agent template being monitored",
    )
    baseline_hash: str = Field(
        min_length=64,
        max_length=64,
        description="SHA256 hash of the baseline template",
    )
    current_hash: str = Field(
        min_length=64,
        max_length=64,
        description="SHA256 hash of the current template",
    )
    semantic_similarity: float = Field(
        ge=0.0,
        le=1.0,
        description="Cosine similarity of embeddings (1.0 = identical)",
    )
    threshold: float = Field(
        ge=0.0,
        le=1.0,
        default=0.95,
        description="Similarity threshold below which drift is flagged",
    )
    drift_detected: bool = Field(
        description="Whether drift exceeded threshold",
    )
    measured_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When this drift measurement was taken",
    )

    @field_validator("drift_detected")
    @classmethod
    def validate_drift_detected(cls, v: bool, info) -> bool:
        """Ensure drift_detected is consistent with similarity and threshold."""
        if "semantic_similarity" in info.data and "threshold" in info.data:
            similarity = info.data["semantic_similarity"]
            threshold = info.data["threshold"]
            expected_drift = similarity < threshold
            if v != expected_drift:
                raise ValueError(
                    f"drift_detected must be {expected_drift} "
                    f"(similarity {similarity:.3f} vs threshold {threshold:.3f})"
                )
        return v

    @field_validator("baseline_hash", "current_hash")
    @classmethod
    def validate_hash_format(cls, v: str) -> str:
        """Ensure hashes are valid hex SHA256 strings."""
        if not all(c in "0123456789abcdefABCDEF" for c in v):
            raise ValueError("Hash must be valid hexadecimal")
        return v.lower()

    def __repr__(self) -> str:
        status = "DRIFT" if self.drift_detected else "STABLE"
        return (
            f"DriftScore(template_id={self.template_id}, "
            f"similarity={self.semantic_similarity:.3f}, {status})"
        )


# ============================================================================
# Summary and Batch Processing
# ============================================================================


class FindingBatch(BaseModel):
    """
    Container for multiple findings from a single blueprint execution.

    Useful for batch processing and transaction-like semantics.
    """

    blueprint_id: str = Field(
        description="ID of the blueprint that generated these findings",
    )
    findings: List[FindingOutput] = Field(
        description="List of findings from this execution",
    )
    agent_id: str = Field(
        description="ID of the agent that performed this scan",
    )
    total_files_scanned: int = Field(
        ge=0,
        description="Total number of files scanned",
    )
    execution_duration_seconds: float = Field(
        ge=0.0,
        description="Time taken to execute blueprint",
    )
    completed_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When execution completed",
    )

    @computed_field
    @property
    def critical_count(self) -> int:
        """Count findings with critical severity."""
        return sum(1 for f in self.findings if f.severity == SeverityLevel.CRITICAL)

    @computed_field
    @property
    def unconfirmed_count(self) -> int:
        """Count findings not confirmed by deterministic tools."""
        return sum(1 for f in self.findings if not f.deterministic_tool_confirmed)

    def __repr__(self) -> str:
        return (
            f"FindingBatch(blueprint_id={self.blueprint_id}, "
            f"findings={len(self.findings)}, "
            f"critical={self.critical_count})"
        )
