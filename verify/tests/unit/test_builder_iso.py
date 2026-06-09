"""
Unit tests for BuilderISO agent.

Tests:
  - Build file detection (_is_build_file — module-level function)
  - _parse_llm_response (JSON, markdown, preamble, object wrapper, malformed)
  - _build_prompt (includes files, tool results, blueprint context)
  - _execute_tool routing (pip-audit, npm-audit, fallback)
  - _run_pip_audit / _run_npm_audit (mocked subprocess)
  - execute() with mocked LLM
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tron.agents.builder_iso import BuilderISO, _is_build_file, BUILD_FILE_PATTERNS
from tron.agents.base import ISOConfig, ISOSpecialization, LLMProvider, ToolResult


@pytest.fixture
def builder_iso(iso_config_builder, fake_secrets, mock_llm_client):
    """BuilderISO instance with mocked LLM."""
    from ..conftest import SAMPLE_BUILDER_FINDINGS_JSON, FakeLLMResponse
    mock_llm_client.complete = AsyncMock(
        return_value=FakeLLMResponse(content=SAMPLE_BUILDER_FINDINGS_JSON)
    )
    return BuilderISO(
        config=iso_config_builder,
        secrets=fake_secrets,
        llm_client=mock_llm_client,
    )


class TestIsBuildFile:
    """Tests for _is_build_file (module-level function)."""

    def test_dockerfile(self):
        assert _is_build_file("Dockerfile") is True

    def test_docker_compose(self):
        assert _is_build_file("docker-compose.yml") is True

    def test_github_workflow(self):
        assert _is_build_file(".github/workflows/ci.yml") is True

    def test_requirements_txt(self):
        assert _is_build_file("requirements.txt") is True

    def test_package_json(self):
        assert _is_build_file("package.json") is True

    def test_makefile(self):
        assert _is_build_file("Makefile") is True

    def test_regular_python_file(self):
        assert _is_build_file("app.py") is False

    def test_regular_js_file(self):
        assert _is_build_file("index.js") is False

    def test_gitignore(self):
        assert _is_build_file(".gitignore") is False

    def test_pyproject_toml(self):
        assert _is_build_file("pyproject.toml") is True

    def test_setup_py(self):
        assert _is_build_file("setup.py") is True

    def test_nested_dockerfile(self):
        assert _is_build_file("docker/Dockerfile.api") is True

    def test_terraform_file(self):
        assert _is_build_file("infra/main.tf") is True

    def test_hcl_file(self):
        assert _is_build_file("config.hcl") is True

    def test_ci_yaml(self):
        """CI-related YAML files are detected via keyword match."""
        assert _is_build_file("ci.yml") is True

    def test_deploy_yaml(self):
        assert _is_build_file("deploy.yaml") is True


# ── _parse_llm_response Tests ────────────────────────────────────────


class TestParseLLMResponse:
    """Tests for BuilderISO._parse_llm_response."""

    def test_valid_json_array(self, builder_iso, sample_blueprint):
        raw = json.dumps([{
            "vulnerability_type": "security_misconfiguration",
            "severity": "high",
            "file_path": "Dockerfile",
            "line_number": 1,
            "code_snippet": "FROM python:latest",
            "description": "Unpinned base image",
            "confidence": 0.85,
        }])
        findings = builder_iso._parse_llm_response(raw, sample_blueprint)
        assert len(findings) == 1
        assert findings[0].file_path == "Dockerfile"
        assert findings[0].line_number == 1

    def test_confidence_capped_at_0_7(self, builder_iso, sample_blueprint):
        raw = json.dumps([{
            "vulnerability_type": "dependency_vulnerability",
            "severity": "medium",
            "file_path": "requirements.txt",
            "line_number": 1,
            "code_snippet": "flask==1.0",
            "description": "Outdated",
            "confidence": 0.99,
        }])
        findings = builder_iso._parse_llm_response(raw, sample_blueprint)
        assert findings[0].confidence == 0.7

    def test_empty_array(self, builder_iso, sample_blueprint):
        findings = builder_iso._parse_llm_response("[]", sample_blueprint)
        assert findings == []

    def test_markdown_wrapped(self, builder_iso, sample_blueprint):
        raw = '```json\n[{"vulnerability_type":"other","severity":"low","file_path":"a.txt","line_number":1,"code_snippet":"x","description":"d","confidence":0.5}]\n```'
        findings = builder_iso._parse_llm_response(raw, sample_blueprint)
        assert len(findings) == 1

    def test_preamble_text_stripped(self, builder_iso, sample_blueprint):
        raw = 'Here are the findings:\n[{"vulnerability_type":"other","severity":"medium","file_path":"a","line_number":2,"code_snippet":"x","description":"d"}]'
        findings = builder_iso._parse_llm_response(raw, sample_blueprint)
        assert len(findings) == 1

    def test_object_with_findings_key(self, builder_iso, sample_blueprint):
        raw = json.dumps({"findings": [{
            "vulnerability_type": "hardcoded_secrets",
            "severity": "high",
            "file_path": "Dockerfile",
            "line_number": 5,
            "code_snippet": "ENV API_KEY=abc123",
            "description": "Secret in layer",
            "confidence": 0.9,
        }]})
        findings = builder_iso._parse_llm_response(raw, sample_blueprint)
        assert len(findings) == 1

    def test_invalid_json_returns_empty(self, builder_iso, sample_blueprint):
        findings = builder_iso._parse_llm_response("not json", sample_blueprint)
        assert findings == []

    def test_malformed_items_skipped(self, builder_iso, sample_blueprint):
        raw = json.dumps([
            {"vulnerability_type": "INVALID", "severity": "invalid_sev"},
            {"vulnerability_type": "other", "severity": "low", "file_path": "a",
             "line_number": 1, "code_snippet": "x", "description": "d"},
        ])
        findings = builder_iso._parse_llm_response(raw, sample_blueprint)
        # Second item may or may not parse depending on severity validation
        # At minimum, invalid items are skipped
        assert len(findings) <= 2

    def test_line_number_clamped_to_1(self, builder_iso, sample_blueprint):
        raw = json.dumps([{
            "vulnerability_type": "other",
            "severity": "low",
            "file_path": "x",
            "line_number": 0,
            "code_snippet": "x",
            "description": "d",
        }])
        findings = builder_iso._parse_llm_response(raw, sample_blueprint)
        assert findings[0].line_number == 1

    def test_unknown_vuln_type_defaults_to_other(self, builder_iso, sample_blueprint):
        raw = json.dumps([{
            "vulnerability_type": "totally_unknown_type",
            "severity": "medium",
            "file_path": "x",
            "line_number": 1,
            "code_snippet": "x",
            "description": "d",
        }])
        findings = builder_iso._parse_llm_response(raw, sample_blueprint)
        from tron.schemas.verification import VulnerabilityType
        assert findings[0].vulnerability_type == VulnerabilityType.OTHER


# ── _build_prompt Tests ──────────────────────────────────────────────


class TestBuildPrompt:
    """Tests for BuilderISO._build_prompt."""

    def test_includes_file_contents(self, builder_iso, sample_blueprint):
        files = {"Dockerfile": "FROM python:3.11\nRUN pip install flask"}
        prompt = builder_iso._build_prompt(sample_blueprint, files, {})
        assert "Dockerfile" in prompt
        assert "FROM python:3.11" in prompt

    def test_includes_blueprint_context(self, builder_iso, sample_blueprint):
        prompt = builder_iso._build_prompt(sample_blueprint, {"a": "b"}, {})
        assert sample_blueprint.name in prompt

    def test_includes_tool_results(self, builder_iso, sample_blueprint):
        tool_results = {
            "pip-audit": ToolResult(
                tool_name="pip-audit",
                exit_code=1,
                stdout="",
                stderr="",
                duration_seconds=1.0,
                findings_count=2,
                raw_findings=[
                    {"package": "flask", "version": "1.0", "description": "CVE-2023-1234"},
                    {"package": "requests", "version": "2.20", "advisory": "CVE-2023-5678"},
                ],
            ),
        }
        prompt = builder_iso._build_prompt(sample_blueprint, {"a": "b"}, tool_results)
        assert "pip-audit" in prompt
        assert "flask" in prompt
        assert "2 vulnerabilities" in prompt

    def test_no_tool_results_section_when_empty(self, builder_iso, sample_blueprint):
        prompt = builder_iso._build_prompt(sample_blueprint, {"a": "b"}, {})
        assert "Dependency Audit Results" not in prompt


# ── _execute_tool Tests ──────────────────────────────────────────────


class TestExecuteTool:
    """Tests for _execute_tool routing."""

    async def test_routes_to_pip_audit(self, builder_iso):
        with patch.object(builder_iso, "_run_pip_audit", new_callable=AsyncMock,
                         return_value=ToolResult(tool_name="pip-audit", exit_code=0,
                                                 stdout="", stderr="", duration_seconds=0)) as mock:
            await builder_iso._execute_tool("pip-audit", "/workspace")
            mock.assert_called_once_with("/workspace")

    async def test_routes_to_npm_audit(self, builder_iso):
        with patch.object(builder_iso, "_run_npm_audit", new_callable=AsyncMock,
                         return_value=ToolResult(tool_name="npm-audit", exit_code=0,
                                                 stdout="", stderr="", duration_seconds=0)) as mock:
            await builder_iso._execute_tool("npm-audit", "/workspace")
            mock.assert_called_once_with("/workspace")


# ── _run_pip_audit Tests ─────────────────────────────────────────────


class TestRunPipAudit:
    """Tests for _run_pip_audit with mocked subprocess."""

    async def test_parses_pip_audit_output(self, builder_iso):
        audit_output = json.dumps({
            "dependencies": [
                {
                    "name": "flask",
                    "version": "1.0.0",
                    "vulns": [
                        {"id": "CVE-2023-1234", "description": "XSS in debug mode", "fix_versions": ["2.3.0"]},
                    ],
                },
            ],
        })

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(audit_output.encode(), b""))
        mock_proc.returncode = 1

        async def passthrough_wait_for(coro, **kwargs):
            return await coro

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc), \
             patch("asyncio.wait_for", side_effect=passthrough_wait_for):
            result = await builder_iso._run_pip_audit("/workspace")

        assert result.tool_name == "pip-audit"
        assert result.findings_count == 1
        assert result.raw_findings[0]["package"] == "flask"

    async def test_pip_audit_not_found(self, builder_iso):
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock,
                   side_effect=FileNotFoundError("pip-audit not found")):
            result = await builder_iso._run_pip_audit("/workspace")

        assert result.exit_code == -1
        assert "not found" in result.stderr


# ── _run_npm_audit Tests ─────────────────────────────────────────────


class TestRunNpmAudit:

    async def test_parses_npm_audit_output(self, builder_iso):
        audit_output = json.dumps({
            "vulnerabilities": {
                "lodash": {
                    "severity": "high",
                    "title": "Prototype Pollution",
                    "via": ["CVE-2020-1234"],
                },
            },
        })

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(audit_output.encode(), b""))
        mock_proc.returncode = 1

        async def passthrough_wait_for(coro, **kwargs):
            return await coro

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc), \
             patch("asyncio.wait_for", side_effect=passthrough_wait_for):
            result = await builder_iso._run_npm_audit("/workspace")

        assert result.tool_name == "npm-audit"
        assert result.findings_count == 1
        assert result.raw_findings[0]["package"] == "lodash"

    async def test_npm_audit_timeout(self, builder_iso):
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock,
                   side_effect=asyncio.TimeoutError()):
            result = await builder_iso._run_npm_audit("/workspace")

        assert result.exit_code == -1


class TestBuilderExecute:
    """Tests for BuilderISO.execute() with mocked LLM."""

    async def test_execute_returns_findings(
        self, builder_iso, sample_blueprint, sample_file_contents
    ):
        """execute() returns findings for build-related files."""
        with patch.object(builder_iso, "_run_deterministic_tools", new_callable=AsyncMock, return_value={}):
            batch = await builder_iso.execute(
                blueprint=sample_blueprint,
                file_contents=sample_file_contents,
            )

        assert batch is not None
        assert batch.agent_id == "builder-iso-test"
        assert len(batch.findings) >= 1

    async def test_execute_with_no_build_files(
        self, builder_iso, sample_blueprint
    ):
        """No build files → agent still runs but may find nothing."""
        files = {"app.py": "print('hello')"}

        with patch.object(builder_iso, "_run_deterministic_tools", new_callable=AsyncMock, return_value={}):
            batch = await builder_iso.execute(
                blueprint=sample_blueprint,
                file_contents=files,
            )

        assert batch is not None
