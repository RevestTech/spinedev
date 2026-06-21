"""
Unit tests for PerformanceISO agent.

Covers:
  - JSON parsing from LLM response (empty array, wrapped, malformed)
  - Finding creation with confidence capping
  - Empty tool results handling
  - No filtered code files fallback
  - Performance category mapping
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from tron.agents.performance_iso import PerformanceISO, _is_code_file
from tron.schemas.verification import (
    Blueprint,
    BlueprintScope,
    VerificationMethod,
)


class TestIsCodeFile:
    """Tests for _is_code_file helper."""

    def test_python_file(self):
        assert _is_code_file("app.py") is True

    def test_javascript_file(self):
        assert _is_code_file("index.js") is True

    def test_typescript_file(self):
        assert _is_code_file("app.ts") is True

    def test_java_file(self):
        assert _is_code_file("Main.java") is True

    def test_go_file(self):
        assert _is_code_file("main.go") is True

    def test_config_file_not_code(self):
        assert _is_code_file("config.yaml") is False

    def test_dockerfile_not_code(self):
        assert _is_code_file("Dockerfile") is False

    def test_package_json_not_code(self):
        assert _is_code_file("package.json") is False

    def test_case_insensitive(self):
        assert _is_code_file("APP.PY") is True
        assert _is_code_file("Main.JAVA") is True


class TestPerformanceISO:
    """Tests for PerformanceISO._parse_llm_response and related methods."""

    @pytest.fixture
    def perf_iso(self, iso_config_performance, fake_secrets, mock_llm_client):
        """PerformanceISO instance."""
        return PerformanceISO(
            config=iso_config_performance,
            secrets=fake_secrets,
            llm_client=mock_llm_client,
        )

    @pytest.fixture
    def sample_blueprint(self):
        """Sample Blueprint for performance testing."""
        return Blueprint(
            id="perf-bp-1",
            name="Performance Analysis",
            description="Test performance blueprint",
            scope=BlueprintScope(
                file_patterns=["*.py"],
                check_types=[],
                languages=["python"],
            ),
            max_tokens=4000,
            max_duration_seconds=300,
            temperature=0.1,
            verification_method=VerificationMethod.DETERMINISTIC_CROSSCHECK,
        )

    def test_parse_llm_response_empty_array(self, perf_iso, sample_blueprint):
        """Empty JSON array should return empty findings."""
        response = "[]"
        findings = perf_iso._parse_llm_response(response, sample_blueprint)
        assert findings == []

    def test_parse_llm_response_valid_json(self, perf_iso, sample_blueprint):
        """Valid JSON should parse correctly."""
        response = json.dumps([
            {
                "vulnerability_type": "other",
                "performance_category": "n_plus_one",
                "severity": "high",
                "file_path": "app.py",
                "line_number": 15,
                "code_snippet": "for item in items: db.query(item)",
                "description": "N+1 query pattern",
                "fix_suggestion": "Use bulk query",
                "estimated_impact": "10x fewer queries",
                "confidence": 0.85,
            },
        ])
        findings = perf_iso._parse_llm_response(response, sample_blueprint)
        assert len(findings) == 1
        assert findings[0].file_path == "app.py"
        assert findings[0].line_number == 15

    def test_parse_llm_response_confidence_capped_at_0_7(self, perf_iso, sample_blueprint):
        """Confidence should be capped at 0.7 for LLM-only findings."""
        response = json.dumps([
            {
                "vulnerability_type": "other",
                "performance_category": "missing_async",
                "severity": "medium",
                "file_path": "async.py",
                "line_number": 5,
                "code_snippet": "requests.get(url)",
                "description": "Blocking I/O",
                "confidence": 0.99,
            },
        ])
        findings = perf_iso._parse_llm_response(response, sample_blueprint)
        assert findings[0].confidence == 0.7

    def test_parse_llm_response_markdown_wrapped(self, perf_iso, sample_blueprint):
        """Should strip markdown code blocks."""
        response = "```json\n[{\"vulnerability_type\":\"other\",\"severity\":\"high\",\"file_path\":\"file_ops.py\",\"line_number\":20,\"code_snippet\":\"f = open('data.txt')\",\"description\":\"Unclosed file\",\"confidence\":0.75}]\n```"
        findings = perf_iso._parse_llm_response(response, sample_blueprint)
        assert len(findings) == 1
        assert findings[0].file_path == "file_ops.py"

    def test_parse_llm_response_preamble_text(self, perf_iso, sample_blueprint):
        """Should strip preamble text before JSON."""
        response = "Here are the issues:\n[{\"vulnerability_type\":\"other\",\"severity\":\"medium\",\"file_path\":\"algo.py\",\"line_number\":10,\"code_snippet\":\"nested\",\"confidence\":0.6}]"
        findings = perf_iso._parse_llm_response(response, sample_blueprint)
        assert len(findings) == 1

    def test_parse_llm_response_object_with_findings_key(self, perf_iso, sample_blueprint):
        """Should handle object wrapper with 'findings' key."""
        response = json.dumps({
            "findings": [
                {
                    "vulnerability_type": "other",
                    "severity": "high",
                    "file_path": "db.py",
                    "line_number": 30,
                    "code_snippet": "SELECT * FROM users",
                    "description": "Missing index",
                    "confidence": 0.7,
                },
            ],
        })
        findings = perf_iso._parse_llm_response(response, sample_blueprint)
        assert len(findings) == 1
        assert findings[0].file_path == "db.py"

    def test_parse_llm_response_invalid_json(self, perf_iso, sample_blueprint):
        """Invalid JSON should return empty list."""
        response = "not valid json"
        findings = perf_iso._parse_llm_response(response, sample_blueprint)
        assert findings == []

    def test_parse_llm_response_malformed_item_skipped(self, perf_iso, sample_blueprint):
        """Malformed items should be skipped."""
        response = json.dumps([
            {
                "vulnerability_type": "other",
                "severity": "high",
                "file_path": "app.py",
                "line_number": 1,
                "code_snippet": "bad",
                "confidence": 0.5,
            },
            {
                "vulnerability_type": "other",
                "severity": "medium",
                "file_path": "cache.py",
                "line_number": 20,
                "code_snippet": "compute_expensive()",
                "description": "Missing cache",
                "confidence": 0.65,
            },
        ])
        findings = perf_iso._parse_llm_response(response, sample_blueprint)
        assert len(findings) >= 1

    def test_parse_llm_response_line_number_clamped_to_1(self, perf_iso, sample_blueprint):
        """Line number 0 should be clamped to 1."""
        response = json.dumps([
            {
                "vulnerability_type": "other",
                "severity": "high",
                "file_path": "memory.py",
                "line_number": 0,
                "code_snippet": "bad",
                "confidence": 0.6,
            },
        ])
        findings = perf_iso._parse_llm_response(response, sample_blueprint)
        assert findings[0].line_number == 1

    def test_parse_includes_performance_category_in_description(self, perf_iso, sample_blueprint):
        """Performance category should be included in description."""
        response = json.dumps([
            {
                "vulnerability_type": "other",
                "performance_category": "blocking_io",
                "severity": "medium",
                "file_path": "io.py",
                "line_number": 10,
                "code_snippet": "time.sleep(1)",
                "description": "Blocking sleep",
                "estimated_impact": "Blocks loop",
                "confidence": 0.65,
            },
        ])
        findings = perf_iso._parse_llm_response(response, sample_blueprint)
        assert "[blocking_io]" in findings[0].description

    def test_parse_finding_fingerprint_set_to_pending(self, perf_iso, sample_blueprint):
        """finding_fingerprint should be set to 'pending'."""
        response = json.dumps([
            {
                "vulnerability_type": "other",
                "severity": "low",
                "file_path": "logging.py",
                "line_number": 25,
                "code_snippet": "logger.debug()",
                "confidence": 0.5,
            },
        ])
        findings = perf_iso._parse_llm_response(response, sample_blueprint)
        assert findings[0].finding_fingerprint == "pending"

    async def test_analyze_with_empty_file_contents(self, perf_iso, sample_blueprint, mock_llm_client):
        """_analyze with empty file_contents should work."""
        mock_llm_client.complete = AsyncMock(
            return_value=MagicMock(
                content="[]",
                total_tokens=100,
                cost_usd=0.001,
            )
        )

        findings = await perf_iso._analyze(
            blueprint=sample_blueprint,
            file_contents={},
            tool_results={},
        )

        assert findings == []

    async def test_analyze_filters_to_code_files(self, perf_iso, sample_blueprint, mock_llm_client):
        """_analyze should filter to code files."""
        mock_llm_client.complete = AsyncMock(
            return_value=MagicMock(
                content="[]",
                total_tokens=100,
                cost_usd=0.001,
            )
        )

        file_contents = {
            "app.py": "print('hello')",
            "config.yaml": "key: value",
        }

        findings = await perf_iso._analyze(
            blueprint=sample_blueprint,
            file_contents=file_contents,
            tool_results={},
        )

        assert isinstance(findings, list)

    async def test_analyze_fallback_to_all_files_if_no_code_files(
        self, perf_iso, sample_blueprint, mock_llm_client
    ):
        """_analyze should fallback to all files if no code files."""
        mock_llm_client.complete = AsyncMock(
            return_value=MagicMock(
                content="[]",
                total_tokens=50,
                cost_usd=0.0005,
            )
        )

        file_contents = {
            "config.yaml": "key: value",
            "README.md": "# README",
        }

        findings = await perf_iso._analyze(
            blueprint=sample_blueprint,
            file_contents=file_contents,
            tool_results={},
        )

        assert findings == []

    async def test_analyze_no_tool_results(self, perf_iso, sample_blueprint, mock_llm_client):
        """_analyze should handle empty tool_results."""
        mock_llm_client.complete = AsyncMock(
            return_value=MagicMock(
                content="[]",
                total_tokens=100,
                cost_usd=0.001,
            )
        )

        findings = await perf_iso._analyze(
            blueprint=sample_blueprint,
            file_contents={"app.py": "print('x')"},
            tool_results={},
        )

        assert findings == []

    def test_build_prompt_includes_files(self, perf_iso, sample_blueprint):
        """_build_prompt should include file contents."""
        files = {"app.py": "print('hello')"}
        prompt = perf_iso._build_prompt(sample_blueprint, files, {})
        assert "app.py" in prompt
        assert "print('hello')" in prompt

    def test_build_prompt_includes_blueprint_name(self, perf_iso, sample_blueprint):
        """_build_prompt should include blueprint name."""
        prompt = perf_iso._build_prompt(sample_blueprint, {"a": "b"}, {})
        assert sample_blueprint.name in prompt
