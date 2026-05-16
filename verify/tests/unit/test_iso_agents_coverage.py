"""
Unit tests for SecurityISO and BuilderISO uncovered lines.

Covers:
  - SecurityISO: LLM client initialization, response parsing edge cases
  - BuilderISO: Empty tool results, no build files fallback
  - Both: JSON parsing branches, analysis method implementations
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tron.agents.base import ISOConfig, ISOSpecialization, LLMProvider, ToolResult
from tron.agents.security_iso import SecurityISO
from tron.agents.builder_iso import BuilderISO
from tron.schemas.verification import (
    Blueprint,
    BlueprintScope,
    FindingBatch,
    VulnerabilityType,
    SeverityLevel,
    VerificationMethod,
)


class TestSecurityISOInitialization:
    """Tests for SecurityISO LLM client initialization."""

    def test_llm_client_initialized_from_anthropic_key(self, iso_config_security, fake_secrets):
        """SecurityISO should initialize LLM client from secrets."""
        with patch("tron.agents.security_iso.LLMClient") as MockLLM:
            MockLLM.return_value = MagicMock()
            iso = SecurityISO(config=iso_config_security, secrets=fake_secrets)
            assert iso._llm is not None
            MockLLM.assert_called_once()

    def test_llm_client_injected_overrides_creation(self, iso_config_security, fake_secrets, mock_llm_client):
        """Injected LLM client should be used."""
        iso = SecurityISO(
            config=iso_config_security,
            secrets=fake_secrets,
            llm_client=mock_llm_client,
        )
        assert iso._llm is mock_llm_client


class TestSecurityISOResponseParsing:
    """Tests for SecurityISO LLM response parsing edge cases."""

    @pytest.fixture
    def security_iso(self, iso_config_security, fake_secrets, mock_llm_client):
        """SecurityISO instance."""
        return SecurityISO(
            config=iso_config_security,
            secrets=fake_secrets,
            llm_client=mock_llm_client,
        )

    @pytest.fixture
    def sample_blueprint(self):
        """Sample blueprint."""
        return Blueprint(
            id="sec-bp-1",
            name="Security Analysis",
            description="Test",
            scope=BlueprintScope(
                file_patterns=["*"],
                check_types=[],
                languages=["python"],
            ),
        )

    def test_parse_response_empty_array(self, security_iso, sample_blueprint):
        """Empty array should return no findings."""
        response = "[]"
        findings = security_iso._parse_llm_response(response, sample_blueprint)
        assert findings == []

    def test_parse_response_markdown_code_block(self, security_iso, sample_blueprint):
        """Should strip markdown code blocks."""
        response = "```json\n[{\"vulnerability_type\":\"sql_injection\",\"severity\":\"critical\",\"file_path\":\"app.py\",\"line_number\":1,\"code_snippet\":\"bad\",\"description\":\"SQL injection\",\"confidence\":0.9}]\n```"
        findings = security_iso._parse_llm_response(response, sample_blueprint)
        assert len(findings) == 1

    def test_parse_response_preamble_text_stripped(self, security_iso, sample_blueprint):
        """Preamble text should be stripped."""
        response = "The vulnerabilities found are:\n[{\"vulnerability_type\":\"xss\",\"severity\":\"high\",\"file_path\":\"template.html\",\"line_number\":5,\"code_snippet\":\"{{ user }}\",\"description\":\"XSS\",\"confidence\":0.85}]"
        findings = security_iso._parse_llm_response(response, sample_blueprint)
        assert len(findings) == 1
        assert findings[0].file_path == "template.html"

    def test_parse_response_object_wrapper(self, security_iso, sample_blueprint):
        """Object wrapper with findings key should work."""
        response = json.dumps({
            "findings": [
                {
                    "vulnerability_type": "hardcoded_secrets",
                    "severity": "critical",
                    "file_path": "config.py",
                    "line_number": 1,
                    "code_snippet": "SECRET = 'x'",
                    "description": "Hardcoded secret",
                    "confidence": 0.95,
                },
            ],
        })
        findings = security_iso._parse_llm_response(response, sample_blueprint)
        assert len(findings) == 1

    def test_parse_response_invalid_json(self, security_iso, sample_blueprint):
        """Invalid JSON should return empty list."""
        response = "not json at all"
        findings = security_iso._parse_llm_response(response, sample_blueprint)
        assert findings == []

    def test_parse_response_malformed_items(self, security_iso, sample_blueprint):
        """Malformed items should be skipped."""
        response = json.dumps([
            {"invalid": "data"},
            {
                "vulnerability_type": "command_injection",
                "severity": "critical",
                "file_path": "cmd.py",
                "line_number": 10,
                "code_snippet": "os.system(cmd)",
                "description": "Command injection",
                "confidence": 0.9,
            },
        ])
        findings = security_iso._parse_llm_response(response, sample_blueprint)
        # Should skip first item, parse second
        assert len(findings) >= 1

    def test_parse_response_confidence_capping(self, security_iso, sample_blueprint):
        """Confidence should be capped at 0.7 for LLM-only."""
        response = json.dumps([
            {
                "vulnerability_type": "broken_auth",
                "severity": "critical",
                "file_path": "auth.py",
                "line_number": 20,
                "code_snippet": "if user:",
                "description": "Auth bypass",
                "confidence": 0.99,
            },
        ])
        findings = security_iso._parse_llm_response(response, sample_blueprint)
        assert findings[0].confidence == 0.7


class TestBuilderISOInitialization:
    """Tests for BuilderISO LLM client initialization."""

    def test_llm_client_initialized_from_openai_key(self, iso_config_builder, fake_secrets):
        """BuilderISO should initialize LLM client."""
        with patch("tron.agents.builder_iso.LLMClient") as MockLLM:
            MockLLM.return_value = MagicMock()
            iso = BuilderISO(config=iso_config_builder, secrets=fake_secrets)
            assert iso._llm is not None
            MockLLM.assert_called_once()

    def test_llm_client_injected_overrides_creation(self, iso_config_builder, fake_secrets, mock_llm_client):
        """Injected client should be used."""
        iso = BuilderISO(
            config=iso_config_builder,
            secrets=fake_secrets,
            llm_client=mock_llm_client,
        )
        assert iso._llm is mock_llm_client


class TestBuilderISOResponseParsing:
    """Tests for BuilderISO LLM response parsing."""

    @pytest.fixture
    def builder_iso(self, iso_config_builder, fake_secrets, mock_llm_client):
        """BuilderISO instance."""
        return BuilderISO(
            config=iso_config_builder,
            secrets=fake_secrets,
            llm_client=mock_llm_client,
        )

    @pytest.fixture
    def sample_blueprint(self):
        """Sample blueprint."""
        return Blueprint(
            id="build-bp-1",
            name="Builder Analysis",
            description="Test",
            scope=BlueprintScope(
                file_patterns=["*"],
                check_types=[],
                languages=["python"],
            ),
        )

    def test_parse_response_empty_array(self, builder_iso, sample_blueprint):
        """Empty array should return no findings."""
        response = "[]"
        findings = builder_iso._parse_llm_response(response, sample_blueprint)
        assert findings == []

    def test_parse_response_markdown_code_block(self, builder_iso, sample_blueprint):
        """Should strip markdown code blocks."""
        response = "```json\n[{\"vulnerability_type\":\"dependency_vulnerability\",\"severity\":\"high\",\"file_path\":\"requirements.txt\",\"line_number\":1,\"code_snippet\":\"flask==1.0\",\"description\":\"Outdated\",\"confidence\":0.8}]\n```"
        findings = builder_iso._parse_llm_response(response, sample_blueprint)
        assert len(findings) == 1

    def test_parse_response_preamble_text(self, builder_iso, sample_blueprint):
        """Preamble should be stripped."""
        response = "Found issues:\n[{\"vulnerability_type\":\"security_misconfiguration\",\"severity\":\"high\",\"file_path\":\"Dockerfile\",\"line_number\":1,\"code_snippet\":\"FROM python:latest\",\"description\":\"Unpinned\",\"confidence\":0.7}]"
        findings = builder_iso._parse_llm_response(response, sample_blueprint)
        assert len(findings) == 1

    def test_parse_response_object_wrapper(self, builder_iso, sample_blueprint):
        """Object with findings key."""
        response = json.dumps({
            "findings": [
                {
                    "vulnerability_type": "hardcoded_secrets",
                    "severity": "critical",
                    "file_path": "Dockerfile",
                    "line_number": 5,
                    "code_snippet": "ENV KEY=value",
                    "description": "Secret in layer",
                    "confidence": 0.9,
                },
            ],
        })
        findings = builder_iso._parse_llm_response(response, sample_blueprint)
        assert len(findings) == 1

    def test_parse_response_invalid_json(self, builder_iso, sample_blueprint):
        """Invalid JSON should return empty."""
        response = "invalid json!"
        findings = builder_iso._parse_llm_response(response, sample_blueprint)
        assert findings == []

    def test_parse_response_malformed_items(self, builder_iso, sample_blueprint):
        """Malformed items skipped."""
        response = json.dumps([
            {"bad": "item"},
            {
                "vulnerability_type": "other",
                "severity": "medium",
                "file_path": "compose.yml",
                "line_number": 10,
                "code_snippet": "service: web",
                "description": "Test",
                "confidence": 0.6,
            },
        ])
        findings = builder_iso._parse_llm_response(response, sample_blueprint)
        assert len(findings) >= 1

    def test_parse_response_unknown_vuln_type_defaults_to_other(self, builder_iso, sample_blueprint):
        """Unknown vulnerability type should default to OTHER."""
        response = json.dumps([
            {
                "vulnerability_type": "unknown_type_xyz",
                "severity": "medium",
                "file_path": "file.py",
                "line_number": 1,
                "code_snippet": "code",
                "description": "Description",
                "confidence": 0.5,
            },
        ])
        findings = builder_iso._parse_llm_response(response, sample_blueprint)
        assert findings[0].vulnerability_type == VulnerabilityType.OTHER

    def test_parse_response_confidence_capping(self, builder_iso, sample_blueprint):
        """Confidence capped at 0.7."""
        response = json.dumps([
            {
                "vulnerability_type": "dependency_vulnerability",
                "severity": "high",
                "file_path": "package.json",
                "line_number": 5,
                "code_snippet": "vulnerable-lib",
                "description": "Known CVE",
                "confidence": 0.99,
            },
        ])
        findings = builder_iso._parse_llm_response(response, sample_blueprint)
        assert findings[0].confidence == 0.7


class TestAnalyzeMethodsWithEmptyToolResults:
    """Tests for analyze methods handling empty tool results."""

    async def test_security_iso_analyze_with_empty_tool_results(
        self, iso_config_security, fake_secrets, mock_llm_client, sample_blueprint
    ):
        """SecurityISO._analyze should handle empty tool_results."""
        mock_llm_client.complete = AsyncMock(
            return_value=MagicMock(
                content="[]",
                total_tokens=100,
                cost_usd=0.001,
            )
        )

        iso = SecurityISO(
            config=iso_config_security,
            secrets=fake_secrets,
            llm_client=mock_llm_client,
        )

        findings = await iso._analyze(
            blueprint=sample_blueprint,
            file_contents={"app.py": "print('x')"},
            tool_results={},
        )

        assert findings == []

    async def test_builder_iso_analyze_with_empty_tool_results(
        self, iso_config_builder, fake_secrets, mock_llm_client, sample_blueprint
    ):
        """BuilderISO._analyze should handle empty tool_results."""
        mock_llm_client.complete = AsyncMock(
            return_value=MagicMock(
                content="[]",
                total_tokens=100,
                cost_usd=0.001,
            )
        )

        iso = BuilderISO(
            config=iso_config_builder,
            secrets=fake_secrets,
            llm_client=mock_llm_client,
        )

        findings = await iso._analyze(
            blueprint=sample_blueprint,
            file_contents={"Dockerfile": "FROM python:3.11"},
            tool_results={},
        )

        assert findings == []


class TestBuildPromptWithToolResults:
    """Tests for prompt building with tool results."""

    def test_security_iso_build_prompt_with_tool_results(
        self, iso_config_security, fake_secrets, mock_llm_client, sample_blueprint
    ):
        """SecurityISO._build_prompt should include tool results."""
        iso = SecurityISO(
            config=iso_config_security,
            secrets=fake_secrets,
            llm_client=mock_llm_client,
        )

        tool_results = {
            "bandit": ToolResult(
                tool_name="bandit",
                exit_code=1,
                stdout="",
                stderr="",
                duration_seconds=1.0,
                findings_count=1,
                raw_findings=[
                    {
                        "file": "app.py",
                        "line": 10,
                        "test_id": "B608",
                        "issue_text": "SQL injection",
                    },
                ],
            ),
        }

        prompt = iso._build_prompt(sample_blueprint, {"app.py": "code"}, tool_results)
        assert "bandit" in prompt
        assert "SQL injection" in prompt

    def test_builder_iso_build_prompt_with_tool_results(
        self, iso_config_builder, fake_secrets, mock_llm_client, sample_blueprint
    ):
        """BuilderISO._build_prompt should include tool results."""
        iso = BuilderISO(
            config=iso_config_builder,
            secrets=fake_secrets,
            llm_client=mock_llm_client,
        )

        tool_results = {
            "pip-audit": ToolResult(
                tool_name="pip-audit",
                exit_code=1,
                stdout="",
                stderr="",
                duration_seconds=1.0,
                findings_count=1,
                raw_findings=[
                    {"package": "flask", "version": "1.0", "description": "CVE"},
                ],
            ),
        }

        prompt = iso._build_prompt(sample_blueprint, {"requirements.txt": "flask==1.0"}, tool_results)
        assert "pip-audit" in prompt
        assert "flask" in prompt
        assert "CVE" in prompt
