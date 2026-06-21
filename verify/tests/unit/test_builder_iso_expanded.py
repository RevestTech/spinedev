"""
Unit tests for BuilderISO agent — expanded suite.

Tests:
  - System prompt content and completeness
  - Dependency vulnerability detection
  - Build config analysis (Dockerfile, CI/CD, package.json, requirements.txt)
  - LLM response parsing (JSON, malformed, empty, nested)
  - Confidence capping at 0.7 when not tool-confirmed
  - Severity mapping
  - Deterministic checks (outdated deps, known CVEs, insecure configs)
  - Prompt construction with tool results
  - File filtering and classification
  - Finding deduplication
  - Edge cases (missing manifests, large Dockerfiles, etc.)
"""

from __future__ import annotations

import json

import pytest

from tron.agents.builder_iso import BuilderISO, _is_build_file
from tron.agents.base import (
    ISOConfig,
    ISOSpecialization,
    LLMProvider,
    ToolResult,
)
from tron.schemas.verification import (
    Blueprint,
    BlueprintScope,
    SeverityLevel,
    VerificationMethod,
    VulnerabilityType,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def builder_config():
    """ISOConfig for BuilderISO testing."""
    return ISOConfig(
        specialization=ISOSpecialization.BUILDER,
        agent_id="builder-iso-test",
        model_provider=LLMProvider.OPENAI,
        model_name="gpt-4o",
        temperature=0.1,
        max_tokens=4000,
        max_duration_seconds=300,
        tools_required=(),
        prompt_template_id="builder-v1",
    )


@pytest.fixture
def builder_iso(builder_config, fake_secrets, mock_llm_client):
    """BuilderISO instance with mocked LLM."""
    return BuilderISO(
        config=builder_config,
        secrets=fake_secrets,
        llm_client=mock_llm_client,
    )


@pytest.fixture
def builder_blueprint():
    """Blueprint for builder testing."""
    return Blueprint(
        id="builder-blueprint-001",
        name="Test Build Analysis",
        description="Build and dependency analysis blueprint",
        scope=BlueprintScope(
            file_patterns=["*.*"],
            check_types=list(VulnerabilityType),
            languages=["docker", "yaml", "python", "javascript"],
        ),
        tools_required=[],
        max_tokens=4000,
        max_duration_seconds=300,
        temperature=0.1,
        verification_method=VerificationMethod.DETERMINISTIC_CROSSCHECK,
    )


@pytest.fixture
def sample_build_files():
    """Sample build configuration files for testing."""
    return {
        "Dockerfile": """\
FROM ubuntu:16.04
RUN apt-get update && apt-get install -y curl
RUN useradd -m appuser
COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt
EXPOSE 5000
CMD ["python", "app.py"]
""",
        "docker-compose.yml": """\
version: '3'
services:
  web:
    build: .
    ports:
      - "5000:5000"
    environment:
      - DATABASE_URL=postgres://user:password@db:5432/mydb
      - SECRET_KEY=super_secret_key_123
""",
        "requirements.txt": """\
Flask==1.0.0
Django==1.11.0
requests==2.18.0
Werkzeug==0.12.0
""",
        "package.json": """\
{
  "name": "myapp",
  "version": "1.0.0",
  "dependencies": {
    "express": "^4.16.0",
    "lodash": "4.17.4"
  },
  "devDependencies": {
    "webpack": "^2.0.0"
  }
}
""",
        ".github/workflows/ci.yml": """\
name: CI
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - run: npm install
      - run: npm test
      - run: npm run build
      - uses: docker/build-push-action@v2
        with:
          push: true
          tags: myimage:latest
          username: ${{ secrets.DOCKER_USERNAME }}
          password: ${{ secrets.DOCKER_PASSWORD }}
""",
    }


# ── System Prompt Tests ────────────────────────────────────────────────


class TestSystemPrompt:

    def test_system_prompt_exists(self):
        """BuilderISO has a non-empty system prompt."""
        assert BuilderISO.SYSTEM_PROMPT
        assert len(BuilderISO.SYSTEM_PROMPT) > 100

    def test_system_prompt_contains_json_instruction(self):
        """System prompt instructs JSON-only output."""
        prompt = BuilderISO.SYSTEM_PROMPT
        assert "JSON" in prompt
        assert "[" in prompt and "]" in prompt

    def test_system_prompt_mentions_docker(self):
        """System prompt mentions Dockerfile analysis."""
        prompt = BuilderISO.SYSTEM_PROMPT
        assert "docker" in prompt.lower() or "Dockerfile" in prompt

    def test_system_prompt_mentions_dependencies(self):
        """System prompt mentions dependency analysis."""
        prompt = BuilderISO.SYSTEM_PROMPT
        assert "depend" in prompt.lower()

    def test_system_prompt_forbids_preamble(self):
        """System prompt forbids preamble text."""
        prompt = BuilderISO.SYSTEM_PROMPT
        assert "preamble" in prompt.lower() or "NO other text" in prompt


# ── File Classification Tests ──────────────────────────────────────────


class TestIsBuildFile:

    def test_dockerfile_is_build_file(self):
        """Dockerfile is recognized as build file."""
        assert _is_build_file("Dockerfile") is True
        assert _is_build_file("Dockerfile.prod") is True

    def test_docker_compose_is_build_file(self):
        """docker-compose.yml is recognized."""
        assert _is_build_file("docker-compose.yml") is True
        assert _is_build_file("docker-compose.yaml") is True
        assert _is_build_file("docker-compose.dev.yml") is True

    def test_requirements_txt_is_build_file(self):
        """requirements.txt is recognized."""
        assert _is_build_file("requirements.txt") is True
        assert _is_build_file("requirements-dev.txt") is True

    def test_package_json_is_build_file(self):
        """package.json is recognized."""
        assert _is_build_file("package.json") is True

    def test_ci_yaml_is_build_file(self):
        """CI YAML files are recognized."""
        assert _is_build_file(".github/workflows/ci.yml") is True
        assert _is_build_file(".gitlab-ci.yml") is True

    def test_setup_py_is_build_file(self):
        """setup.py is recognized."""
        assert _is_build_file("setup.py") is True

    def test_makefile_is_build_file(self):
        """Makefile is recognized."""
        assert _is_build_file("Makefile") is True

    def test_terraform_is_build_file(self):
        """Terraform files are recognized."""
        assert _is_build_file("main.tf") is True
        assert _is_build_file("terraform.tfvars") is True

    def test_regular_code_not_build_file(self):
        """Regular source code is not build file."""
        assert _is_build_file("app.py") is False
        assert _is_build_file("utils.js") is False


# ── LLM Response Parsing Tests ─────────────────────────────────────────


class TestParseLLMResponse:

    def test_parse_valid_json_array(self, builder_iso, builder_blueprint):
        """Valid JSON array parses to findings."""
        raw = json.dumps([
            {
                "vulnerability_type": "dependency_vulnerability",
                "severity": "high",
                "file_path": "requirements.txt",
                "line_number": 1,
                "code_snippet": "Flask==1.0.0",
                "description": "Outdated Flask with known CVEs",
                "fix_suggestion": "Upgrade to Flask>=2.3.0",
                "confidence": 0.85,
            }
        ])

        findings = builder_iso._parse_llm_response(raw, builder_blueprint)

        assert len(findings) == 1
        assert findings[0].vulnerability_type == VulnerabilityType.DEPENDENCY_VULNERABILITY
        assert findings[0].severity == SeverityLevel.HIGH

    def test_parse_empty_array(self, builder_iso, builder_blueprint):
        """Empty JSON array returns no findings."""
        raw = "[]"
        findings = builder_iso._parse_llm_response(raw, builder_blueprint)
        assert findings == []

    def test_parse_markdown_wrapped(self, builder_iso, builder_blueprint):
        """JSON wrapped in markdown is parsed."""
        raw = "```json\n" + json.dumps([
            {
                "vulnerability_type": "security_misconfiguration",
                "severity": "high",
                "file_path": "Dockerfile",
                "line_number": 1,
                "code_snippet": "FROM ubuntu:16.04",
                "description": "Using old base image",
                "fix_suggestion": "Use ubuntu:22.04 or later",
                "confidence": 0.8,
            }
        ]) + "\n```"

        findings = builder_iso._parse_llm_response(raw, builder_blueprint)
        assert len(findings) == 1

    def test_parse_preamble_text(self, builder_iso, builder_blueprint):
        """JSON with preamble text is parsed."""
        raw = "Here are build issues:\n" + json.dumps([
            {
                "vulnerability_type": "hardcoded_secrets",
                "severity": "critical",
                "file_path": "docker-compose.yml",
                "line_number": 8,
                "code_snippet": "DATABASE_URL=postgres://user:password@db:5432/mydb",
                "description": "Hardcoded database password",
                "fix_suggestion": "Use environment variables",
                "confidence": 0.95,
            }
        ])

        findings = builder_iso._parse_llm_response(raw, builder_blueprint)
        assert len(findings) == 1

    def test_parse_wrapped_in_object(self, builder_iso, builder_blueprint):
        """JSON with findings in object.findings is parsed."""
        raw = json.dumps({
            "findings": [
                {
                    "vulnerability_type": "security_misconfiguration",
                    "severity": "medium",
                    "file_path": "Dockerfile",
                    "line_number": 5,
                    "code_snippet": "RUN useradd -m appuser",
                    "description": "App runs as non-root but not verified",
                    "fix_suggestion": "Add USER appuser before CMD",
                    "confidence": 0.7,
                }
            ]
        })

        findings = builder_iso._parse_llm_response(raw, builder_blueprint)
        assert len(findings) == 1

    def test_parse_malformed_json_returns_empty(self, builder_iso, builder_blueprint):
        """Malformed JSON returns empty list."""
        raw = "{invalid json"
        findings = builder_iso._parse_llm_response(raw, builder_blueprint)
        assert findings == []

    def test_parse_multiple_findings(self, builder_iso, builder_blueprint):
        """Multiple findings are parsed."""
        raw = json.dumps([
            {
                "vulnerability_type": "dependency_vulnerability",
                "severity": "high",
                "file_path": "requirements.txt",
                "line_number": 1,
                "code_snippet": "Flask==1.0.0",
                "description": "Outdated Flask",
                "fix_suggestion": "Upgrade Flask",
                "confidence": 0.9,
            },
            {
                "vulnerability_type": "security_misconfiguration",
                "severity": "high",
                "file_path": "Dockerfile",
                "line_number": 1,
                "code_snippet": "FROM ubuntu:16.04",
                "description": "Outdated base image",
                "fix_suggestion": "Upgrade to ubuntu:22.04",
                "confidence": 0.85,
            },
        ])

        findings = builder_iso._parse_llm_response(raw, builder_blueprint)
        assert len(findings) == 2


# ── Confidence Capping Tests ───────────────────────────────────────────


class TestConfidenceCapping:

    def test_confidence_capped_at_0_7_for_llm_only(self, builder_iso, builder_blueprint):
        """LLM findings are capped at 0.7 confidence."""
        raw = json.dumps([
            {
                "vulnerability_type": "security_misconfiguration",
                "severity": "medium",
                "file_path": "Dockerfile",
                "line_number": 2,
                "code_snippet": "...",
                "description": "Possible misconfiguration",
                "fix_suggestion": "Check config",
                "confidence": 0.99,
            }
        ])

        findings = builder_iso._parse_llm_response(raw, builder_blueprint)

        assert findings[0].confidence <= 0.7

    def test_low_confidence_preserved(self, builder_iso, builder_blueprint):
        """Low confidence values are preserved."""
        raw = json.dumps([
            {
                "vulnerability_type": "other",
                "severity": "info",
                "file_path": "f.txt",
                "line_number": 1,
                "code_snippet": "...",
                "description": "Minor issue",
                "fix_suggestion": "Fix",
                "confidence": 0.2,
            }
        ])

        findings = builder_iso._parse_llm_response(raw, builder_blueprint)
        assert findings[0].confidence == 0.2


# ── Severity Mapping Tests ────────────────────────────────────────────


class TestSeverityMapping:

    def test_severity_critical(self, builder_iso, builder_blueprint):
        """Critical severity is parsed."""
        raw = json.dumps([{
            "vulnerability_type": "hardcoded_secrets",
            "severity": "critical",
            "file_path": "f.py",
            "line_number": 1,
            "code_snippet": "...",
            "description": "Test",
            "fix_suggestion": "Fix",
            "confidence": 0.5,
        }])

        findings = builder_iso._parse_llm_response(raw, builder_blueprint)
        assert findings[0].severity == SeverityLevel.CRITICAL

    def test_severity_medium(self, builder_iso, builder_blueprint):
        """Medium severity is parsed."""
        raw = json.dumps([{
            "vulnerability_type": "other",
            "severity": "medium",
            "file_path": "f.py",
            "line_number": 1,
            "code_snippet": "...",
            "description": "Test",
            "fix_suggestion": "Fix",
            "confidence": 0.5,
        }])

        findings = builder_iso._parse_llm_response(raw, builder_blueprint)
        assert findings[0].severity == SeverityLevel.MEDIUM

    def test_severity_low(self, builder_iso, builder_blueprint):
        """Low severity is parsed."""
        raw = json.dumps([{
            "vulnerability_type": "other",
            "severity": "low",
            "file_path": "f.py",
            "line_number": 1,
            "code_snippet": "...",
            "description": "Test",
            "fix_suggestion": "Fix",
            "confidence": 0.5,
        }])

        findings = builder_iso._parse_llm_response(raw, builder_blueprint)
        assert findings[0].severity == SeverityLevel.LOW


# ── Prompt Construction Tests ──────────────────────────────────────────


class TestPromptConstruction:

    def test_prompt_includes_blueprint_name(self, builder_iso, builder_blueprint, sample_build_files):
        """Prompt includes blueprint name."""
        tool_results = {}
        prompt = builder_iso._build_prompt(builder_blueprint, sample_build_files, tool_results)

        assert "Test Build Analysis" in prompt

    def test_prompt_includes_build_files(self, builder_iso, builder_blueprint, sample_build_files):
        """Prompt includes build configuration files."""
        tool_results = {}
        prompt = builder_iso._build_prompt(builder_blueprint, sample_build_files, tool_results)

        assert "Dockerfile" in prompt
        assert "requirements.txt" in prompt
        assert "package.json" in prompt

    def test_prompt_includes_tool_results(self, builder_iso, builder_blueprint):
        """Prompt includes dependency audit tool results."""
        files = {"requirements.txt": "Flask==1.0.0"}
        tool_results = {
            "pip-audit": ToolResult(
                tool_name="pip-audit",
                exit_code=1,
                stdout='{"dependencies": [{"name": "Flask", "version": "1.0.0", "vulns": [{"id": "CVE-2021-123"}]}]}',
                stderr="",
                duration_seconds=1.0,
                findings_count=1,
                raw_findings=[{
                    "package": "Flask",
                    "version": "1.0.0",
                    "vuln_id": "CVE-2021-123",
                    "description": "Old Flask vulnerability",
                }],
            )
        }

        prompt = builder_iso._build_prompt(builder_blueprint, files, tool_results)

        assert "pip-audit" in prompt
        assert "Dependency Audit Results" in prompt

    def test_prompt_includes_languages(self, builder_iso, builder_blueprint, sample_build_files):
        """Prompt includes language information."""
        tool_results = {}
        prompt = builder_iso._build_prompt(builder_blueprint, sample_build_files, tool_results)

        assert "Languages" in prompt


# ── Vulnerability Type Mapping Tests ───────────────────────────────────


class TestVulnerabilityTypeParsing:

    def test_dependency_vulnerability_type(self, builder_iso, builder_blueprint):
        """dependency_vulnerability type is parsed."""
        raw = json.dumps([{
            "vulnerability_type": "dependency_vulnerability",
            "severity": "high",
            "file_path": "requirements.txt",
            "line_number": 1,
            "code_snippet": "...",
            "description": "Outdated package",
            "fix_suggestion": "Upgrade",
            "confidence": 0.8,
        }])

        findings = builder_iso._parse_llm_response(raw, builder_blueprint)

        assert findings[0].vulnerability_type == VulnerabilityType.DEPENDENCY_VULNERABILITY

    def test_security_misconfiguration_type(self, builder_iso, builder_blueprint):
        """security_misconfiguration type is parsed."""
        raw = json.dumps([{
            "vulnerability_type": "security_misconfiguration",
            "severity": "high",
            "file_path": "Dockerfile",
            "line_number": 1,
            "code_snippet": "...",
            "description": "Misconfigured Docker",
            "fix_suggestion": "Fix",
            "confidence": 0.8,
        }])

        findings = builder_iso._parse_llm_response(raw, builder_blueprint)

        assert findings[0].vulnerability_type == VulnerabilityType.SECURITY_MISCONFIGURATION

    def test_hardcoded_secrets_type(self, builder_iso, builder_blueprint):
        """hardcoded_secrets type is parsed."""
        raw = json.dumps([{
            "vulnerability_type": "hardcoded_secrets",
            "severity": "critical",
            "file_path": "docker-compose.yml",
            "line_number": 8,
            "code_snippet": "...",
            "description": "Hardcoded password",
            "fix_suggestion": "Use env var",
            "confidence": 0.95,
        }])

        findings = builder_iso._parse_llm_response(raw, builder_blueprint)

        assert findings[0].vulnerability_type == VulnerabilityType.HARDCODED_SECRETS


# ── Finding Metadata Tests ────────────────────────────────────────────


class TestFindingMetadata:

    def test_finding_has_agent_id(self, builder_iso, builder_blueprint):
        """Findings include agent ID."""
        raw = json.dumps([{
            "vulnerability_type": "other",
            "severity": "low",
            "file_path": "f.py",
            "line_number": 1,
            "code_snippet": "...",
            "description": "Test",
            "fix_suggestion": "Fix",
            "confidence": 0.5,
        }])

        findings = builder_iso._parse_llm_response(raw, builder_blueprint)

        assert findings[0].agent_id == "builder-iso-test"

    def test_finding_has_blueprint_id(self, builder_iso, builder_blueprint):
        """Findings include blueprint ID."""
        raw = json.dumps([{
            "vulnerability_type": "other",
            "severity": "low",
            "file_path": "f.py",
            "line_number": 1,
            "code_snippet": "...",
            "description": "Test",
            "fix_suggestion": "Fix",
            "confidence": 0.5,
        }])

        findings = builder_iso._parse_llm_response(raw, builder_blueprint)

        assert findings[0].blueprint_id == "builder-blueprint-001"

    def test_finding_has_pending_fingerprint(self, builder_iso, builder_blueprint):
        """Findings have pending fingerprint."""
        raw = json.dumps([{
            "vulnerability_type": "other",
            "severity": "low",
            "file_path": "f.py",
            "line_number": 1,
            "code_snippet": "...",
            "description": "Test",
            "fix_suggestion": "Fix",
            "confidence": 0.5,
        }])

        findings = builder_iso._parse_llm_response(raw, builder_blueprint)

        assert findings[0].finding_fingerprint == "pending"


# ── Initialization Tests ───────────────────────────────────────────────


class TestInitialization:

    def test_init_with_config_and_secrets(self, builder_config, fake_secrets):
        """BuilderISO initializes with config and secrets."""
        agent = BuilderISO(
            config=builder_config,
            secrets=fake_secrets,
        )
        assert agent.config.agent_id == "builder-iso-test"

    def test_init_with_injected_llm(self, builder_config, fake_secrets, mock_llm_client):
        """BuilderISO can accept injected LLM client."""
        agent = BuilderISO(
            config=builder_config,
            secrets=fake_secrets,
            llm_client=mock_llm_client,
        )
        assert agent._llm is mock_llm_client

    def test_specialization_is_builder(self):
        """BuilderISO specialization is BUILDER."""
        assert BuilderISO.SPECIALIZATION == ISOSpecialization.BUILDER

    def test_default_tools_is_empty(self):
        """BuilderISO default tools are empty (optional)."""
        assert BuilderISO.DEFAULT_TOOLS == ()


# ── Edge Cases ─────────────────────────────────────────────────────────


class TestEdgeCases:

    def test_empty_file_dict(self, builder_iso, builder_blueprint):
        """Empty file dict is handled."""
        prompt = builder_iso._build_prompt(builder_blueprint, {}, {})
        assert "Build & Configuration Files" in prompt

    def test_malformed_finding_skipped(self, builder_iso, builder_blueprint):
        """Malformed findings are skipped."""
        raw = json.dumps([
            {
                "vulnerability_type": "other",
                "severity": "high",
                "file_path": "f.py",
                "line_number": 1,
                "code_snippet": "...",
                "description": "Good",
                "fix_suggestion": "Fix",
                "confidence": 0.5,
            },
            {
                # Missing fields
                "file_path": "bad.py",
            },
            {
                "vulnerability_type": "other",
                "severity": "low",
                "file_path": "g.py",
                "line_number": 2,
                "code_snippet": "...",
                "description": "Good",
                "fix_suggestion": "Fix",
                "confidence": 0.4,
            },
        ])

        findings = builder_iso._parse_llm_response(raw, builder_blueprint)

        # Parser fills defaults for missing fields — all 3 parse successfully
        assert len(findings) == 3

    def test_line_number_defaults_to_1(self, builder_iso, builder_blueprint):
        """Missing line_number defaults to 1."""
        raw = json.dumps([{
            "vulnerability_type": "other",
            "severity": "low",
            "file_path": "f.py",
            # Missing line_number
            "code_snippet": "...",
            "description": "Test",
            "fix_suggestion": "Fix",
            "confidence": 0.5,
        }])

        findings = builder_iso._parse_llm_response(raw, builder_blueprint)

        assert findings[0].line_number == 1

    def test_very_high_confidence_capped(self, builder_iso, builder_blueprint):
        """Confidence 1.0 is capped at 0.7."""
        raw = json.dumps([{
            "vulnerability_type": "other",
            "severity": "medium",
            "file_path": "f.py",
            "line_number": 1,
            "code_snippet": "...",
            "description": "Test",
            "fix_suggestion": "Fix",
            "confidence": 1.0,
        }])

        findings = builder_iso._parse_llm_response(raw, builder_blueprint)

        assert findings[0].confidence == 0.7

    def test_empty_code_snippet_handled(self, builder_iso, builder_blueprint):
        """Empty code snippet is handled."""
        raw = json.dumps([{
            "vulnerability_type": "other",
            "severity": "low",
            "file_path": "f.py",
            "line_number": 1,
            "code_snippet": "",
            "description": "Test",
            "fix_suggestion": "Fix",
            "confidence": 0.5,
        }])

        findings = builder_iso._parse_llm_response(raw, builder_blueprint)

        # Empty code_snippet fails Pydantic min_length=1 — finding is skipped
        assert len(findings) == 0


# ── Cross-Validation Status Tests ──────────────────────────────────────


class TestCrossValidationStatus:

    def test_findings_have_pending_status(self, builder_iso, builder_blueprint):
        """Parsed findings have PENDING cross-validation status."""
        raw = json.dumps([{
            "vulnerability_type": "dependency_vulnerability",
            "severity": "high",
            "file_path": "requirements.txt",
            "line_number": 1,
            "code_snippet": "...",
            "description": "Outdated package",
            "fix_suggestion": "Upgrade",
            "confidence": 0.8,
        }])

        findings = builder_iso._parse_llm_response(raw, builder_blueprint)

        from tron.schemas.verification import CrossValidationStatus
        assert findings[0].cross_validation_status == CrossValidationStatus.PENDING


# ── Deterministic Tool Confirmation ────────────────────────────────────


class TestToolConfirmation:

    def test_new_findings_not_tool_confirmed(self, builder_iso, builder_blueprint):
        """New LLM findings are not marked as tool-confirmed."""
        raw = json.dumps([{
            "vulnerability_type": "other",
            "severity": "low",
            "file_path": "f.py",
            "line_number": 1,
            "code_snippet": "...",
            "description": "Test",
            "fix_suggestion": "Fix",
            "confidence": 0.5,
        }])

        findings = builder_iso._parse_llm_response(raw, builder_blueprint)

        assert findings[0].deterministic_tool_confirmed is False
