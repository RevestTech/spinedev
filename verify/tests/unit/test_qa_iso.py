"""
Unit tests for QAISO agent.

Tests:
  - Deterministic tool pre-pass (test file detection, regex analysis)
  - LLM response parsing (JSON, markdown-wrapped, malformed)
  - Finding construction (QA categories, confidence capping)
  - Prompt construction
  - File classification helpers
  - execute() with mocked LLM
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from tron.agents.qa_iso import QAISO, QA_VULN_TYPE_MAP
from tron.agents.base import ISOConfig, ISOSpecialization, LLMProvider, ToolResult
from tron.schemas.verification import (
    Blueprint,
    BlueprintScope,
    FindingOutput,
    SeverityLevel,
    VerificationMethod,
    VulnerabilityType,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def qa_config():
    """ISOConfig for QAISO testing."""
    return ISOConfig(
        specialization=ISOSpecialization.QA,
        agent_id="qa-iso-test",
        model_provider=LLMProvider.OPENAI,
        model_name="gpt-4o",
        temperature=0.1,
        max_tokens=4000,
        max_duration_seconds=300,
        tools_required=(),
        prompt_template_id="qa-v1",
    )


@pytest.fixture
def qa_iso(qa_config, fake_secrets, mock_llm_client):
    """QAISO instance with mocked LLM."""
    return QAISO(
        config=qa_config,
        secrets=fake_secrets,
        llm_client=mock_llm_client,
    )


@pytest.fixture
def qa_blueprint():
    """Blueprint for QA testing."""
    return Blueprint(
        id="qa-blueprint-001",
        name="Test Quality Analysis",
        description="QA analysis blueprint",
        scope=BlueprintScope(
            file_patterns=["*.*"],
            check_types=list(VulnerabilityType),
            languages=["python"],
        ),
        tools_required=[],
        max_tokens=4000,
        max_duration_seconds=300,
        temperature=0.1,
        verification_method=VerificationMethod.DETERMINISTIC_CROSSCHECK,
    )


@pytest.fixture
def sample_test_files():
    """Sample test files for QAISO analysis."""
    return {
        "tests/test_auth.py": """\
import pytest
from app import authenticate

class TestAuth:
    def test_valid_login(self):
        result = authenticate("user", "pass123")
        assert result.success is True

    def test_empty_password(self):
        result = authenticate("user", "")
        # Missing assertion!

    @pytest.mark.skip(reason="flaky")
    def test_timeout_handling(self):
        import time
        time.sleep(10)
        assert True
""",
        "tests/test_api.py": """\
import pytest

def test_get_users():
    response = client.get("/users")
    assert response.status_code == 200

def test_create_user():
    response = client.post("/users", json={"name": "test"})
    assert response.status_code == 201
""",
        "app.py": """\
from flask import Flask, request

app = Flask(__name__)

def authenticate(username, password):
    if not password:
        raise ValueError("Password required")
    return {"success": True}

@app.route("/users")
def get_users():
    return []
""",
    }


# ── File Classification Tests ────────────────────────────────────────


class TestIsTestFile:

    def test_test_prefix(self):
        assert QAISO._is_test_file("test_auth.py") is True

    def test_test_suffix(self):
        assert QAISO._is_test_file("auth_test.py") is True

    def test_tests_directory(self):
        assert QAISO._is_test_file("tests/test_auth.py") is True
        assert QAISO._is_test_file("src/tests/test_api.py") is True

    def test_test_directory(self):
        assert QAISO._is_test_file("test/test_api.py") is True

    def test_not_test_file(self):
        assert QAISO._is_test_file("app.py") is False
        assert QAISO._is_test_file("utils.py") is False

    def test_non_python_ignored(self):
        assert QAISO._is_test_file("test_auth.js") is False
        assert QAISO._is_test_file("tests/test_api.ts") is False


class TestIsConfigFile:

    def test_config_files(self):
        assert QAISO._is_config_file("pytest.ini") is True
        assert QAISO._is_config_file("pyproject.toml") is True
        assert QAISO._is_config_file("setup.cfg") is True
        assert QAISO._is_config_file("requirements.txt") is True
        assert QAISO._is_config_file("Dockerfile") is True

    def test_yaml_files(self):
        assert QAISO._is_config_file("ci.yml") is True
        assert QAISO._is_config_file("config.yaml") is True

    def test_not_config(self):
        assert QAISO._is_config_file("app.py") is False
        assert QAISO._is_config_file("utils.py") is False


# ── Deterministic Pre-Pass Tests ─────────────────────────────────────


class TestDeterministicTools:

    def test_counts_test_files(self, qa_iso, sample_test_files):
        """Pre-pass counts test files correctly."""
        metadata = qa_iso._run_deterministic_tools(sample_test_files)

        assert metadata["test_file_count"] == 2  # test_auth.py, test_api.py

    def test_counts_test_functions(self, qa_iso, sample_test_files):
        """Pre-pass counts test functions via regex."""
        metadata = qa_iso._run_deterministic_tools(sample_test_files)

        # test_auth.py: test_valid_login, test_empty_password, test_timeout_handling = 3
        # test_api.py: test_get_users, test_create_user = 2
        assert metadata["test_function_count"] == 5

    def test_counts_skipped_tests(self, qa_iso, sample_test_files):
        """Pre-pass detects @pytest.mark.skip decorators."""
        metadata = qa_iso._run_deterministic_tools(sample_test_files)

        assert metadata["skipped_test_count"] == 1

    def test_detects_pytest_config(self, qa_iso):
        """Pre-pass notes presence of pytest config files."""
        files = {
            "pyproject.toml": "[tool.pytest.ini_options]\ntestpaths = ['tests']",
            "tests/test_x.py": "def test_x(): pass",
        }
        metadata = qa_iso._run_deterministic_tools(files)
        assert "pyproject.toml" in metadata["pytest_config"]

    def test_no_test_files(self, qa_iso):
        """Pre-pass handles no test files gracefully."""
        files = {"app.py": "x = 1", "utils.py": "y = 2"}
        metadata = qa_iso._run_deterministic_tools(files)

        assert metadata["test_file_count"] == 0
        assert metadata["test_function_count"] == 0


# ── LLM Response Parsing Tests ───────────────────────────────────────


class TestParseLLMResponse:

    def test_parse_valid_json_array(self, qa_iso, qa_blueprint):
        """Valid JSON array → QA findings."""
        raw = json.dumps([
            {
                "vulnerability_type": "other",
                "qa_category": "missing_assertions",
                "severity": "high",
                "file_path": "tests/test_auth.py",
                "line_number": 10,
                "code_snippet": "def test_empty_password(self):",
                "description": "Test has no assert statements",
                "fix_suggestion": "Add assertion for expected behavior",
                "confidence": 0.85,
            }
        ])

        findings = qa_iso._parse_llm_response(raw, qa_blueprint)

        assert len(findings) == 1
        assert findings[0].vulnerability_type == VulnerabilityType.OTHER
        assert findings[0].severity == SeverityLevel.HIGH
        assert "[missing_assertions]" in findings[0].description

    def test_confidence_capped_at_0_7(self, qa_iso, qa_blueprint):
        """QA findings are LLM-only → confidence capped at 0.7."""
        raw = json.dumps([
            {
                "vulnerability_type": "other",
                "qa_category": "dead_test",
                "severity": "medium",
                "file_path": "tests/test_x.py",
                "line_number": 1,
                "code_snippet": "pass",
                "description": "Dead test",
                "confidence": 0.95,
            }
        ])

        findings = qa_iso._parse_llm_response(raw, qa_blueprint)

        assert len(findings) == 1
        assert findings[0].confidence <= 0.7

    def test_parse_markdown_wrapped(self, qa_iso, qa_blueprint):
        """JSON wrapped in markdown code blocks is handled."""
        raw = "```json\n" + json.dumps([
            {
                "vulnerability_type": "other",
                "qa_category": "flaky_test_pattern",
                "severity": "medium",
                "file_path": "t.py",
                "line_number": 1,
                "code_snippet": "time.sleep(10)",
                "description": "Flaky test uses sleep",
                "confidence": 0.6,
            }
        ]) + "\n```"

        findings = qa_iso._parse_llm_response(raw, qa_blueprint)
        assert len(findings) == 1

    def test_parse_preamble_text(self, qa_iso, qa_blueprint):
        """JSON with preamble text before array is handled."""
        raw = "Here are the findings:\n" + json.dumps([
            {
                "vulnerability_type": "other",
                "qa_category": "test_isolation",
                "severity": "high",
                "file_path": "t.py",
                "line_number": 1,
                "code_snippet": "shared_state = {}",
                "description": "Tests share mutable state",
                "confidence": 0.6,
            }
        ])

        findings = qa_iso._parse_llm_response(raw, qa_blueprint)
        assert len(findings) == 1

    def test_parse_empty_array(self, qa_iso, qa_blueprint):
        """Empty array → no findings."""
        findings = qa_iso._parse_llm_response("[]", qa_blueprint)
        assert findings == []

    def test_parse_malformed_json(self, qa_iso, qa_blueprint):
        """Malformed JSON → empty findings (no crash)."""
        findings = qa_iso._parse_llm_response("not json at all", qa_blueprint)
        assert findings == []

    def test_parse_dict_with_findings_key(self, qa_iso, qa_blueprint):
        """Dict with 'findings' key is handled."""
        raw = json.dumps({
            "findings": [
                {
                    "vulnerability_type": "other",
                    "qa_category": "duplicate_test",
                    "severity": "low",
                    "file_path": "t.py",
                    "line_number": 1,
                    "code_snippet": "pass",
                    "description": "Duplicate test",
                    "confidence": 0.5,
                }
            ]
        })

        findings = qa_iso._parse_llm_response(raw, qa_blueprint)
        assert len(findings) == 1

    def test_all_qa_categories_mapped(self, qa_iso, qa_blueprint):
        """All QA categories are mapped to VulnerabilityType."""
        for category in QA_VULN_TYPE_MAP:
            raw = json.dumps([
                {
                    "vulnerability_type": "other",
                    "qa_category": category,
                    "severity": "medium",
                    "file_path": "t.py",
                    "line_number": 1,
                    "code_snippet": "pass",
                    "description": f"Test issue: {category}",
                    "confidence": 0.5,
                }
            ])

            findings = qa_iso._parse_llm_response(raw, qa_blueprint)
            assert len(findings) == 1, f"Failed for category: {category}"


# ── Prompt Construction Tests ────────────────────────────────────────


class TestBuildPrompt:

    def test_prompt_includes_test_files(self, qa_iso, qa_blueprint, sample_test_files):
        """Prompt includes test file contents."""
        test_files = {
            p: c for p, c in sample_test_files.items()
            if qa_iso._is_test_file(p)
        }
        metadata = qa_iso._run_deterministic_tools(sample_test_files)

        prompt = qa_iso._build_prompt(
            qa_blueprint, test_files, sample_test_files, metadata, {}
        )

        assert "test_auth.py" in prompt
        assert "test_api.py" in prompt
        assert "test_valid_login" in prompt

    def test_prompt_includes_metadata(self, qa_iso, qa_blueprint, sample_test_files):
        """Prompt includes test metadata summary."""
        test_files = {
            p: c for p, c in sample_test_files.items()
            if qa_iso._is_test_file(p)
        }
        metadata = qa_iso._run_deterministic_tools(sample_test_files)

        prompt = qa_iso._build_prompt(
            qa_blueprint, test_files, sample_test_files, metadata, {}
        )

        assert "Test files:" in prompt
        assert "Test functions:" in prompt
        assert "Skipped tests:" in prompt

    def test_prompt_includes_source_context(self, qa_iso, qa_blueprint, sample_test_files):
        """Prompt includes source file context (for coverage analysis)."""
        test_files = {
            p: c for p, c in sample_test_files.items()
            if qa_iso._is_test_file(p)
        }
        metadata = qa_iso._run_deterministic_tools(sample_test_files)

        prompt = qa_iso._build_prompt(
            qa_blueprint, test_files, sample_test_files, metadata, {}
        )

        assert "Source Files" in prompt
        assert "app.py" in prompt


# ── QA Vuln Type Map Tests ───────────────────────────────────────────


class TestQAVulnTypeMap:

    def test_all_categories_map_to_other(self):
        """All QA categories map to VulnerabilityType.OTHER."""
        for category, vuln_type in QA_VULN_TYPE_MAP.items():
            assert vuln_type == VulnerabilityType.OTHER

    def test_expected_categories_exist(self):
        """Key QA categories are defined."""
        expected = {
            "dead_test", "missing_assertions", "missing_edge_cases",
            "test_isolation", "flaky_test_pattern", "incomplete_coverage",
            "slow_test", "duplicate_test", "missing_error_handling",
            "hardcoded_values",
        }
        assert set(QA_VULN_TYPE_MAP.keys()) == expected


# ── Execute Tests ────────────────────────────────────────────────────


class TestExecute:

    async def test_execute_no_test_files(self, qa_iso, qa_blueprint):
        """execute() with no test files returns empty findings."""
        files = {"app.py": "x = 1"}
        result = await qa_iso._analyze(qa_blueprint, files, {})
        assert result == []

    async def test_execute_with_test_files(self, qa_iso, qa_blueprint, mock_llm_client, sample_test_files):
        """execute() calls LLM and returns parsed findings."""
        qa_findings = json.dumps([
            {
                "vulnerability_type": "other",
                "qa_category": "missing_assertions",
                "severity": "high",
                "file_path": "tests/test_auth.py",
                "line_number": 10,
                "code_snippet": "def test_empty_password(self):",
                "description": "Missing assertion in test",
                "fix_suggestion": "Add assert",
                "confidence": 0.8,
            }
        ])

        from tests.conftest import FakeLLMResponse
        mock_llm_client.complete = AsyncMock(
            return_value=FakeLLMResponse(content=qa_findings)
        )

        result = await qa_iso._analyze(qa_blueprint, sample_test_files, {})

        assert len(result) == 1
        assert result[0].severity == SeverityLevel.HIGH
        assert result[0].confidence <= 0.7  # Capped
