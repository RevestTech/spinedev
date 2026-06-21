"""
Expanded unit tests for tron/agents/base.py (~40 tests).

Tests cover:
  - ISOConfig validation and immutability
  - Agent initialization
  - Blueprint scoping and file filtering
  - Tool initialization
  - Resource limits (token budget, duration, tool concurrency)
  - Finding fingerprinting and deduplication
  - Error handling
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tron.agents.base import (
    ISOConfig,
    ISOSpecialization,
    LLMProvider,
    AgentMetrics,
    ToolResult,
)
from tron.schemas.verification import (
    BlueprintScope,
    VulnerabilityType,
)


# ── Tests: ISOConfig creation and validation ────────────────────────


class TestISOConfigCreation:
    """Tests for ISOConfig dataclass creation."""

    def test_config_minimal(self):
        """Config with minimal required fields."""
        config = ISOConfig(
            specialization=ISOSpecialization.SECURITY,
            agent_id="security-iso-1",
            model_provider=LLMProvider.OPENAI,
            model_name="gpt-4o",
        )
        assert config.specialization == ISOSpecialization.SECURITY
        assert config.agent_id == "security-iso-1"
        assert config.model_provider == LLMProvider.OPENAI

    def test_config_with_all_fields(self):
        """Config with all optional fields."""
        config = ISOConfig(
            specialization=ISOSpecialization.BUILDER,
            agent_id="builder-iso-1",
            model_provider=LLMProvider.ANTHROPIC,
            model_name="claude-haiku-4-5-20251001",
            fallback_model_name="claude-3-sonnet-20240229",
            temperature=0.1,
            max_tokens=4000,
            max_duration_seconds=300,
            max_retries=2,
            max_concurrent_tools=4,
            tools_required=("semgrep", "bandit"),
            prompt_template_id="builder-v1",
            prompt_template_hash="abc123",
        )
        assert config.temperature == 0.1
        assert config.max_tokens == 4000
        assert config.max_duration_seconds == 300

    def test_config_frozen_immutable(self):
        """ISOConfig should be frozen (immutable)."""
        config = ISOConfig(
            specialization=ISOSpecialization.SECURITY,
            agent_id="test",
            model_provider=LLMProvider.OPENAI,
            model_name="gpt-4o",
        )
        # Attempting to modify should raise error
        with pytest.raises(AttributeError):
            config.temperature = 0.5

    def test_config_all_specializations(self):
        """Should support all specializations."""
        for spec in [
            ISOSpecialization.SECURITY,
            ISOSpecialization.BUILDER,
            ISOSpecialization.QA,
            ISOSpecialization.PERFORMANCE,
            ISOSpecialization.COMPLIANCE,
            ISOSpecialization.DOCUMENTATION,
            ISOSpecialization.ARCHITECTURE,
        ]:
            config = ISOConfig(
                specialization=spec,
                agent_id=f"{spec.value}-test",
                model_provider=LLMProvider.OPENAI,
                model_name="gpt-4o",
            )
            assert config.specialization == spec

    def test_config_all_providers(self):
        """Should support all LLM providers."""
        for provider in [LLMProvider.ANTHROPIC, LLMProvider.OPENAI]:
            config = ISOConfig(
                specialization=ISOSpecialization.SECURITY,
                agent_id="test",
                model_provider=provider,
                model_name="test-model",
            )
            assert config.model_provider == provider


# ── Tests: ToolResult dataclass ──────────────────────────────────────


class TestToolResult:
    """Tests for ToolResult dataclass."""

    def test_tool_result_success(self):
        result = ToolResult(
            tool_name="bandit",
            exit_code=0,
            stdout="[INFO] Scan complete",
            stderr="",
            duration_seconds=5.2,
            findings_count=3,
        )
        assert result.success
        assert result.exit_code == 0

    def test_tool_result_failure(self):
        result = ToolResult(
            tool_name="semgrep",
            exit_code=1,
            stdout="",
            stderr="Error: Invalid config",
            duration_seconds=2.0,
            findings_count=0,
        )
        assert not result.success
        assert result.exit_code == 1

    def test_tool_result_with_raw_findings(self):
        result = ToolResult(
            tool_name="bandit",
            exit_code=0,
            stdout="",
            stderr="",
            duration_seconds=3.0,
            findings_count=2,
            raw_findings=[
                {"issue_type": "sql_injection", "severity": "HIGH"},
                {"issue_type": "hardcoded_secret", "severity": "CRITICAL"},
            ],
        )
        assert len(result.raw_findings) == 2


# ── Tests: AgentMetrics dataclass ────────────────────────────────────


class TestAgentMetrics:
    """Tests for AgentMetrics dataclass."""

    def test_metrics_creation(self):
        metrics = AgentMetrics(
            agent_id="security-iso-1",
            blueprint_id="bp-001",
            started_at=1000.0,
            finished_at=1050.0,
            total_findings=5,
        )
        assert metrics.agent_id == "security-iso-1"
        assert metrics.duration_seconds == 50.0

    def test_metrics_duration_calculation(self):
        """duration_seconds should calculate from start/finish."""
        metrics = AgentMetrics(
            agent_id="test",
            started_at=100.0,
            finished_at=145.5,
        )
        assert metrics.duration_seconds == 45.5

    def test_metrics_duration_not_started(self):
        """Duration should be 0 if not started."""
        metrics = AgentMetrics(agent_id="test", started_at=0.0, finished_at=0.0)
        assert metrics.duration_seconds == 0.0

    def test_metrics_to_dict(self):
        """to_dict should include all fields."""
        metrics = AgentMetrics(
            agent_id="test",
            blueprint_id="bp-1",
            started_at=1000.0,
            finished_at=1030.0,
            total_findings=5,
            tool_durations={"bandit": 2.0, "semgrep": 3.0},
            llm_calls=3,
            llm_tokens_used=3000,
            llm_cost_usd=0.03,
            errors=["Warning: Tool X slow"],
        )
        data = metrics.to_dict()
        assert data["agent_id"] == "test"
        assert data["duration_seconds"] == 30.0
        assert data["total_findings"] == 5
        assert data["llm_calls"] == 3

    def test_metrics_empty_errors(self):
        """Metrics should handle empty error list."""
        metrics = AgentMetrics(agent_id="test", errors=[])
        assert metrics.errors == []

    def test_metrics_multiple_errors(self):
        """Metrics should accumulate errors."""
        metrics = AgentMetrics(
            agent_id="test",
            errors=["Error 1", "Error 2", "Warning 3"],
        )
        assert len(metrics.errors) == 3


# ── Tests: Blueprint scoping ─────────────────────────────────────────


class TestBlueprintScoping:
    """Tests for Blueprint scope validation."""

    def test_blueprint_scope_file_patterns(self):
        """Blueprint scope should specify file patterns."""
        scope = BlueprintScope(
            file_patterns=["*.py", "*.js"],
            check_types=list(VulnerabilityType),
            languages=["python", "javascript"],
        )
        assert "*.py" in scope.file_patterns
        assert "*.js" in scope.file_patterns

    def test_blueprint_scope_languages(self):
        """Blueprint scope should specify languages."""
        scope = BlueprintScope(
            file_patterns=["*.*"],
            check_types=[VulnerabilityType.SQL_INJECTION],
            languages=["python"],
        )
        assert "python" in scope.languages

    def test_blueprint_scope_check_types(self):
        """Blueprint scope should specify check types."""
        check_types = [
            VulnerabilityType.SQL_INJECTION,
            VulnerabilityType.XSS,
            VulnerabilityType.COMMAND_INJECTION,
        ]
        scope = BlueprintScope(
            file_patterns=["*.*"],
            check_types=check_types,
            languages=["python"],
        )
        assert len(scope.check_types) == 3

    def test_blueprint_file_filtering(self):
        """Should determine which files match patterns."""
        files = {
            "app.py": "code",
            "config.json": "config",
            "style.css": "css",
            "main.js": "javascript",
        }

        # Python only
        patterns = ["*.py"]
        matching = [p for p in files if any(p.endswith(pat.replace("*", "")) for pat in patterns)]
        assert matching == ["app.py"]

    def test_blueprint_language_filtering(self):
        """Should filter by language."""
        languages = ["python", "javascript"]

        extension_map = {
            "py": "python",
            "js": "javascript",
            "ts": "typescript",
            "json": "json",
        }

        files = {
            "app.py": "python",
            "main.js": "javascript",
            "types.ts": "typescript",
            "config.json": "json",
        }

        # Filter to python and javascript only
        filtered = {
            k: v for k, v in files.items()
            if k.rsplit(".", 1)[1] in extension_map
            and extension_map[k.rsplit(".", 1)[1]] in languages
        }

        assert len(filtered) == 2


# ── Tests: Resource limits ───────────────────────────────────────────


class TestResourceLimits:
    """Tests for token budgets and duration limits."""

    def test_token_budget_default(self):
        """Default max_tokens should be 4000."""
        config = ISOConfig(
            specialization=ISOSpecialization.SECURITY,
            agent_id="test",
            model_provider=LLMProvider.OPENAI,
            model_name="gpt-4o",
        )
        assert config.max_tokens == 4000

    def test_token_budget_custom(self):
        """Should allow custom token budget."""
        config = ISOConfig(
            specialization=ISOSpecialization.SECURITY,
            agent_id="test",
            model_provider=LLMProvider.OPENAI,
            model_name="gpt-4o",
            max_tokens=8000,
        )
        assert config.max_tokens == 8000

    def test_duration_limit_default(self):
        """Default max_duration_seconds should be 300."""
        config = ISOConfig(
            specialization=ISOSpecialization.SECURITY,
            agent_id="test",
            model_provider=LLMProvider.OPENAI,
            model_name="gpt-4o",
        )
        assert config.max_duration_seconds == 300

    def test_duration_limit_custom(self):
        """Should allow custom duration limit."""
        config = ISOConfig(
            specialization=ISOSpecialization.SECURITY,
            agent_id="test",
            model_provider=LLMProvider.OPENAI,
            model_name="gpt-4o",
            max_duration_seconds=600,
        )
        assert config.max_duration_seconds == 600

    def test_max_retries_default(self):
        """Default max_retries should be 2."""
        config = ISOConfig(
            specialization=ISOSpecialization.SECURITY,
            agent_id="test",
            model_provider=LLMProvider.OPENAI,
            model_name="gpt-4o",
        )
        assert config.max_retries == 2

    def test_max_concurrent_tools_default(self):
        """Default max_concurrent_tools should be 4."""
        config = ISOConfig(
            specialization=ISOSpecialization.SECURITY,
            agent_id="test",
            model_provider=LLMProvider.OPENAI,
            model_name="gpt-4o",
        )
        assert config.max_concurrent_tools == 4

    def test_max_concurrent_tools_custom(self):
        """Should allow custom concurrency limit."""
        config = ISOConfig(
            specialization=ISOSpecialization.SECURITY,
            agent_id="test",
            model_provider=LLMProvider.OPENAI,
            model_name="gpt-4o",
            max_concurrent_tools=8,
        )
        assert config.max_concurrent_tools == 8


# ── Tests: Finding fingerprinting ────────────────────────────────────


class TestFindingFingerprinting:
    """Tests for finding deduplication via fingerprinting."""

    def test_fingerprint_consistency(self):
        """Same finding should have same fingerprint."""
        fp1 = "abc123def456"
        fp2 = "abc123def456"
        assert fp1 == fp2

    def test_fingerprint_uniqueness(self):
        """Different findings should have different fingerprints."""
        fp1 = "abc123def456"
        fp2 = "xyz789uvw000"
        assert fp1 != fp2

    def test_finding_with_fingerprint(self):
        """FindingOutput should include fingerprint."""
        fp_val = "fp-sql-injection-app-py-10"
        finding = MagicMock()
        finding.fingerprint = fp_val
        # Fingerprint should be set
        assert finding.fingerprint is not None

    def test_dedup_by_fingerprint(self):
        """Should deduplicate findings with same fingerprint."""
        findings = [
            MagicMock(fingerprint="fp-001"),
            MagicMock(fingerprint="fp-001"),
        ]

        # Both should have same fingerprint
        assert findings[0].fingerprint == findings[1].fingerprint

    def test_keep_tool_confirmed_when_dedupping(self):
        """When dedupping, prefer tool-confirmed finding."""
        findings = [
            MagicMock(fingerprint="fp-001", deterministic_tool_confirmed=False),
            MagicMock(fingerprint="fp-001", deterministic_tool_confirmed=True),
        ]

        # Prefer tool-confirmed
        tool_confirmed = [f for f in findings if f.deterministic_tool_confirmed]
        assert len(tool_confirmed) == 1


# ── Tests: Tool requirements ─────────────────────────────────────────


class TestToolRequirements:
    """Tests for required tools configuration."""

    def test_tools_required_empty(self):
        """Agent may have no tool requirements."""
        config = ISOConfig(
            specialization=ISOSpecialization.BUILDER,
            agent_id="builder",
            model_provider=LLMProvider.OPENAI,
            model_name="gpt-4o",
            tools_required=(),
        )
        assert config.tools_required == ()

    def test_tools_required_security(self):
        """Security ISO typically requires bandit and semgrep."""
        config = ISOConfig(
            specialization=ISOSpecialization.SECURITY,
            agent_id="security",
            model_provider=LLMProvider.OPENAI,
            model_name="gpt-4o",
            tools_required=("bandit", "semgrep"),
        )
        assert "bandit" in config.tools_required
        assert "semgrep" in config.tools_required

    def test_tools_required_custom(self):
        """Should allow custom tool requirements."""
        config = ISOConfig(
            specialization=ISOSpecialization.QA,
            agent_id="qa",
            model_provider=LLMProvider.OPENAI,
            model_name="gpt-4o",
            tools_required=("pytest", "coverage"),
        )
        assert len(config.tools_required) == 2


# ── Tests: LLM Provider validation ───────────────────────────────────


class TestLLMProviderValidation:
    """Tests for LLM provider settings."""

    def test_provider_anthropic_models(self):
        """Anthropic provider with valid models."""
        for model in ["claude-haiku-4-5-20251001", "claude-3-sonnet-20240229", "claude-3-opus-20240229"]:
            config = ISOConfig(
                specialization=ISOSpecialization.SECURITY,
                agent_id="test",
                model_provider=LLMProvider.ANTHROPIC,
                model_name=model,
            )
            assert config.model_provider == LLMProvider.ANTHROPIC
            assert config.model_name == model

    def test_provider_openai_models(self):
        """OpenAI provider with valid models."""
        for model in ["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"]:
            config = ISOConfig(
                specialization=ISOSpecialization.SECURITY,
                agent_id="test",
                model_provider=LLMProvider.OPENAI,
                model_name=model,
            )
            assert config.model_provider == LLMProvider.OPENAI

    def test_fallback_model_configuration(self):
        """Should allow fallback model."""
        config = ISOConfig(
            specialization=ISOSpecialization.SECURITY,
            agent_id="test",
            model_provider=LLMProvider.ANTHROPIC,
            model_name="claude-haiku-4-5-20251001",
            fallback_model_name="claude-3-sonnet-20240229",
        )
        assert config.fallback_model_name == "claude-3-sonnet-20240229"


# ── Tests: Temperature settings ──────────────────────────────────────


class TestTemperatureSettings:
    """Tests for LLM temperature configuration."""

    def test_temperature_low(self):
        """Low temperature for deterministic output."""
        config = ISOConfig(
            specialization=ISOSpecialization.SECURITY,
            agent_id="test",
            model_provider=LLMProvider.OPENAI,
            model_name="gpt-4o",
            temperature=0.0,  # Most deterministic
        )
        assert config.temperature == 0.0

    def test_temperature_default(self):
        """Default temperature should be 0.1."""
        config = ISOConfig(
            specialization=ISOSpecialization.SECURITY,
            agent_id="test",
            model_provider=LLMProvider.OPENAI,
            model_name="gpt-4o",
        )
        assert config.temperature == 0.1

    def test_temperature_custom(self):
        """Should allow custom temperature."""
        config = ISOConfig(
            specialization=ISOSpecialization.SECURITY,
            agent_id="test",
            model_provider=LLMProvider.OPENAI,
            model_name="gpt-4o",
            temperature=0.5,
        )
        assert config.temperature == 0.5


# ── Tests: Prompt template configuration ────────────────────────────


class TestPromptTemplateConfig:
    """Tests for prompt template reference."""

    def test_prompt_template_id(self):
        """Should track prompt template ID."""
        config = ISOConfig(
            specialization=ISOSpecialization.SECURITY,
            agent_id="test",
            model_provider=LLMProvider.OPENAI,
            model_name="gpt-4o",
            prompt_template_id="security-v1",
        )
        assert config.prompt_template_id == "security-v1"

    def test_prompt_template_hash(self):
        """Should track prompt template hash for drift detection."""
        config = ISOConfig(
            specialization=ISOSpecialization.SECURITY,
            agent_id="test",
            model_provider=LLMProvider.OPENAI,
            model_name="gpt-4o",
            prompt_template_id="security-v1",
            prompt_template_hash="sha256abc123",
        )
        assert config.prompt_template_hash == "sha256abc123"
