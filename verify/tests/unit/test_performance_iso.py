"""
Unit tests for PerformanceISO agent.

Tests:
  - Code file detection (_is_code_file — module-level function)
  - execute() with mocked LLM
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from tron.agents.performance_iso import PerformanceISO, _is_code_file


@pytest.fixture
def perf_iso(iso_config_performance, fake_secrets, mock_llm_client):
    """PerformanceISO instance with mocked LLM."""
    from tests.conftest import SAMPLE_PERFORMANCE_FINDINGS_JSON, FakeLLMResponse
    mock_llm_client.complete = AsyncMock(
        return_value=FakeLLMResponse(content=SAMPLE_PERFORMANCE_FINDINGS_JSON)
    )
    return PerformanceISO(
        config=iso_config_performance,
        secrets=fake_secrets,
        llm_client=mock_llm_client,
    )


class TestIsCodeFile:
    """Tests for _is_code_file (module-level function)."""

    def test_python_file(self):
        assert _is_code_file("app.py") is True

    def test_javascript_file(self):
        assert _is_code_file("index.js") is True

    def test_typescript_file(self):
        assert _is_code_file("component.tsx") is True

    def test_go_file(self):
        assert _is_code_file("main.go") is True

    def test_dockerfile_is_not_code(self):
        assert _is_code_file("Dockerfile") is False

    def test_yaml_is_not_code(self):
        assert _is_code_file("config.yml") is False

    def test_requirements_is_not_code(self):
        assert _is_code_file("requirements.txt") is False

    def test_json_is_not_code(self):
        assert _is_code_file("package.json") is False


class TestPerformanceExecute:
    """Tests for PerformanceISO.execute() with mocked LLM."""

    async def test_execute_returns_findings(
        self, perf_iso, sample_blueprint, sample_file_contents
    ):
        """execute() returns performance findings."""
        with patch.object(perf_iso, "_run_deterministic_tools", new_callable=AsyncMock, return_value={}):
            batch = await perf_iso.execute(
                blueprint=sample_blueprint,
                file_contents=sample_file_contents,
            )

        assert batch is not None
        assert batch.agent_id == "performance-iso-test"
        assert len(batch.findings) >= 1
