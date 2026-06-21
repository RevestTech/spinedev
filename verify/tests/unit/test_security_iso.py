"""
Unit tests for SecurityISO agent.

Tests:
  - LLM response parsing (JSON, markdown-wrapped, preamble, malformed)
  - Finding construction (severity, confidence capping, fingerprints)
  - Prompt construction (includes files, tool results)
  - Bandit severity mapping
  - execute() integration with mocked LLM
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tron.agents.security_iso import SecurityISO, BANDIT_SEVERITY_MAP, BANDIT_VULN_TYPE_MAP
from tron.agents.base import ToolResult
from tron.schemas.verification import (
    SeverityLevel,
    VulnerabilityType,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def security_iso(iso_config_security, fake_secrets, mock_llm_client):
    """SecurityISO instance with mocked LLM."""
    return SecurityISO(
        config=iso_config_security,
        secrets=fake_secrets,
        llm_client=mock_llm_client,
    )


# ── _parse_llm_response Tests ────────────────────────────────────────


class TestParseLLMResponse:
    """Tests for SecurityISO._parse_llm_response."""

    def test_parse_valid_json_array(self, security_iso, sample_blueprint):
        """Valid JSON array → findings with correct fields."""
        raw = json.dumps([
            {
                "vulnerability_type": "sql_injection",
                "severity": "critical",
                "file_path": "app.py",
                "line_number": 12,
                "code_snippet": "cursor.execute(...)",
                "description": "SQL injection",
                "confidence": 0.95,
            }
        ])

        findings = security_iso._parse_llm_response(raw, sample_blueprint)

        assert len(findings) == 1
        assert findings[0].vulnerability_type == VulnerabilityType.SQL_INJECTION
        assert findings[0].severity == SeverityLevel.CRITICAL
        assert findings[0].file_path == "app.py"
        assert findings[0].line_number == 12

    def test_confidence_capped_at_0_7(self, security_iso, sample_blueprint):
        """LLM-only findings capped at 0.7 confidence (not tool-confirmed)."""
        raw = json.dumps([
            {
                "vulnerability_type": "xss",
                "severity": "high",
                "file_path": "a.py",
                "line_number": 1,
                "code_snippet": "x",
                "description": "XSS",
                "confidence": 0.99,
            }
        ])

        findings = security_iso._parse_llm_response(raw, sample_blueprint)

        assert findings[0].confidence == 0.7
        assert findings[0].deterministic_tool_confirmed is False

    def test_parse_empty_array(self, security_iso, sample_blueprint):
        """Empty array → no findings."""
        findings = security_iso._parse_llm_response("[]", sample_blueprint)
        assert findings == []

    def test_parse_markdown_wrapped(self, security_iso, sample_blueprint):
        """Handles markdown code blocks around JSON."""
        raw = '```json\n[{"vulnerability_type":"xss","severity":"medium","file_path":"a.py","line_number":1,"code_snippet":"x","description":"d","confidence":0.5}]\n```'

        findings = security_iso._parse_llm_response(raw, sample_blueprint)
        assert len(findings) == 1
        assert findings[0].vulnerability_type == VulnerabilityType.XSS

    def test_parse_with_preamble(self, security_iso, sample_blueprint):
        """Strips text preamble before JSON array."""
        raw = 'Here are the findings:\n[{"vulnerability_type":"hardcoded_secrets","severity":"high","file_path":"a.py","line_number":5,"code_snippet":"x","description":"d","confidence":0.8}]'

        findings = security_iso._parse_llm_response(raw, sample_blueprint)
        assert len(findings) == 1
        assert findings[0].vulnerability_type == VulnerabilityType.HARDCODED_SECRETS

    def test_parse_object_with_findings_key(self, security_iso, sample_blueprint):
        """Handles LLM wrapping findings in an object."""
        raw = json.dumps({
            "findings": [
                {
                    "vulnerability_type": "command_injection",
                    "severity": "critical",
                    "file_path": "a.py",
                    "line_number": 1,
                    "code_snippet": "os.system(cmd)",
                    "description": "Command injection",
                    "confidence": 0.9,
                }
            ]
        })

        findings = security_iso._parse_llm_response(raw, sample_blueprint)
        assert len(findings) == 1
        assert findings[0].vulnerability_type == VulnerabilityType.COMMAND_INJECTION

    def test_parse_invalid_json(self, security_iso, sample_blueprint):
        """Malformed JSON → returns empty list."""
        findings = security_iso._parse_llm_response("not json at all", sample_blueprint)
        assert findings == []

    def test_parse_skips_malformed_findings(self, security_iso, sample_blueprint):
        """Malformed individual items are skipped, valid ones kept."""
        raw = json.dumps([
            {
                "vulnerability_type": "INVALID_TYPE",
                "severity": "critical",
                "file_path": "a.py",
                "line_number": 1,
                "code_snippet": "x",
                "description": "d",
            },
            {
                "vulnerability_type": "sql_injection",
                "severity": "high",
                "file_path": "b.py",
                "line_number": 5,
                "code_snippet": "y",
                "description": "Valid finding",
                "confidence": 0.6,
            },
        ])

        findings = security_iso._parse_llm_response(raw, sample_blueprint)
        assert len(findings) == 1
        assert findings[0].file_path == "b.py"

    def test_line_number_minimum_is_1(self, security_iso, sample_blueprint):
        """Line number 0 or negative → clamps to 1."""
        raw = json.dumps([
            {
                "vulnerability_type": "xss",
                "severity": "low",
                "file_path": "a.py",
                "line_number": 0,
                "code_snippet": "x",
                "description": "d",
            }
        ])

        findings = security_iso._parse_llm_response(raw, sample_blueprint)
        assert findings[0].line_number == 1

    def test_default_severity_is_medium(self, security_iso, sample_blueprint):
        """Missing severity → defaults to medium."""
        raw = json.dumps([
            {
                "vulnerability_type": "xss",
                "file_path": "a.py",
                "line_number": 1,
                "code_snippet": "x",
                "description": "d",
            }
        ])

        findings = security_iso._parse_llm_response(raw, sample_blueprint)
        assert findings[0].severity == SeverityLevel.MEDIUM


# ── _build_prompt Tests ───────────────────────────────────────────────


class TestBuildPrompt:
    """Tests for SecurityISO._build_prompt."""

    def test_includes_file_contents(self, security_iso, sample_blueprint):
        """Prompt includes source file contents."""
        files = {"app.py": "import os\nos.system('ls')"}
        prompt = security_iso._build_prompt(sample_blueprint, files, {})

        assert "app.py" in prompt
        assert "import os" in prompt
        assert "os.system" in prompt

    def test_includes_blueprint_context(self, security_iso, sample_blueprint):
        """Prompt includes blueprint name and check types."""
        prompt = security_iso._build_prompt(sample_blueprint, {"a.py": "x"}, {})

        assert sample_blueprint.name in prompt
        assert "sql_injection" in prompt

    def test_includes_tool_results(self, security_iso, sample_blueprint):
        """Prompt includes deterministic tool findings."""
        tool_results = {
            "bandit": ToolResult(
                tool_name="bandit",
                exit_code=1,
                stdout="",
                stderr="",
                duration_seconds=1.0,
                findings_count=1,
                raw_findings=[{
                    "file": "app.py",
                    "line": 12,
                    "test_id": "B608",
                    "issue_text": "SQL injection",
                }],
            ),
        }

        prompt = security_iso._build_prompt(
            sample_blueprint, {"app.py": "x"}, tool_results
        )

        assert "bandit" in prompt.lower()
        assert "B608" in prompt


# ── execute() Integration Test ────────────────────────────────────────


class TestExecute:
    """Tests for the full SecurityISO.execute() with mocked LLM."""

    async def test_execute_returns_finding_batch(
        self, security_iso, sample_blueprint, sample_file_contents
    ):
        """execute() returns FindingBatch with findings from mocked LLM."""
        # The mock_llm_client returns SAMPLE_SECURITY_FINDINGS_JSON
        with patch.object(security_iso, "_run_deterministic_tools", new_callable=AsyncMock, return_value={}):
            batch = await security_iso.execute(
                blueprint=sample_blueprint,
                file_contents=sample_file_contents,
            )

        assert batch is not None
        assert batch.agent_id == "security-iso-test"
        assert batch.blueprint_id == sample_blueprint.id
        assert len(batch.findings) >= 1

    async def test_execute_timeout_returns_empty(
        self, security_iso, sample_blueprint, sample_file_contents
    ):
        """Timeout → empty findings, error in metrics."""
        # Override blueprint to very short timeout
        sample_blueprint.max_duration_seconds = 0  # instant timeout

        with patch.object(security_iso, "_run_deterministic_tools", new_callable=AsyncMock, side_effect=asyncio.TimeoutError):
            batch = await security_iso.execute(
                blueprint=sample_blueprint,
                file_contents=sample_file_contents,
            )

        assert len(batch.findings) == 0

    async def test_execute_exception_returns_empty(
        self, security_iso, sample_blueprint, sample_file_contents
    ):
        """Exception → empty findings, error recorded."""
        with patch.object(security_iso, "_run_deterministic_tools", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
            batch = await security_iso.execute(
                blueprint=sample_blueprint,
                file_contents=sample_file_contents,
            )

        assert len(batch.findings) == 0
        assert security_iso.metrics is not None


# ── Bandit Mapping Tests ──────────────────────────────────────────────


class TestBanditMappings:
    """Tests for Bandit severity and vulnerability type maps."""

    def test_all_severities_mapped(self):
        """All expected Bandit severities have a mapping."""
        for sev in ("HIGH", "MEDIUM", "LOW", "UNDEFINED"):
            assert sev in BANDIT_SEVERITY_MAP

    def test_sql_injection_rules_mapped(self):
        """B608 (SQL concat) maps to SQL_INJECTION."""
        assert BANDIT_VULN_TYPE_MAP["B608"] == VulnerabilityType.SQL_INJECTION

    def test_command_injection_rules_mapped(self):
        """B602 (subprocess shell) maps to COMMAND_INJECTION."""
        assert BANDIT_VULN_TYPE_MAP["B602"] == VulnerabilityType.COMMAND_INJECTION

    def test_pickle_rules_mapped(self):
        """B301 (pickle) maps to INSECURE_DESERIALIZATION."""
        assert BANDIT_VULN_TYPE_MAP["B301"] == VulnerabilityType.INSECURE_DESERIALIZATION

    def test_hardcoded_secrets_mapped(self):
        """B105/B106/B107 map to HARDCODED_SECRETS."""
        for rule in ("B105", "B106", "B107"):
            assert BANDIT_VULN_TYPE_MAP[rule] == VulnerabilityType.HARDCODED_SECRETS


# ── Tool Confirmation Tests ───────────────────────────────────────────


class TestToolConfirmation:
    """Tests for _check_tool_confirmation."""

    def test_matching_file_and_line(self, security_iso):
        """Tool finding on same file + nearby line → confirmed."""
        finding = MagicMock()
        finding.file_path = "app.py"
        finding.line_number = 12

        tool_results = {
            "bandit": ToolResult(
                tool_name="bandit",
                exit_code=1,
                stdout="",
                stderr="",
                duration_seconds=1.0,
                findings_count=1,
                raw_findings=[{"file": "app.py", "line": 12, "test_id": "B608"}],
            ),
        }

        confirming = security_iso._check_tool_confirmation(finding, tool_results)
        assert "bandit" in confirming

    def test_no_match_different_file(self, security_iso):
        """Tool finding on different file → not confirmed."""
        finding = MagicMock()
        finding.file_path = "app.py"
        finding.line_number = 12

        tool_results = {
            "bandit": ToolResult(
                tool_name="bandit",
                exit_code=1,
                stdout="",
                stderr="",
                duration_seconds=1.0,
                findings_count=1,
                raw_findings=[{"file": "other.py", "line": 12}],
            ),
        }

        confirming = security_iso._check_tool_confirmation(finding, tool_results)
        assert confirming == []

    def test_line_proximity_within_5(self, security_iso):
        """Tool finding within ±5 lines → confirmed."""
        finding = MagicMock()
        finding.file_path = "app.py"
        finding.line_number = 12

        tool_results = {
            "bandit": ToolResult(
                tool_name="bandit",
                exit_code=1,
                stdout="",
                stderr="",
                duration_seconds=1.0,
                findings_count=1,
                raw_findings=[{"file": "app.py", "line": 16}],
            ),
        }

        confirming = security_iso._check_tool_confirmation(finding, tool_results)
        assert "bandit" in confirming

    def test_line_too_far_away(self, security_iso):
        """Tool finding > 5 lines away → not confirmed."""
        finding = MagicMock()
        finding.file_path = "app.py"
        finding.line_number = 12

        tool_results = {
            "bandit": ToolResult(
                tool_name="bandit",
                exit_code=1,
                stdout="",
                stderr="",
                duration_seconds=1.0,
                findings_count=1,
                raw_findings=[{"file": "app.py", "line": 100}],
            ),
        }

        confirming = security_iso._check_tool_confirmation(finding, tool_results)
        assert confirming == []


# ── _execute_tool Routing Tests ──────────────────────────────────────


class TestExecuteToolRouting:

    async def test_routes_to_bandit(self, security_iso):
        # _execute_tool now requires file_contents; it writes files to a
        # temp dir and calls _run_bandit with that temp dir (not workspace_root).
        with patch.object(security_iso, "_run_bandit", new_callable=AsyncMock,
                         return_value=ToolResult(tool_name="bandit", exit_code=0,
                                                 stdout="", stderr="", duration_seconds=0)) as mock:
            await security_iso._execute_tool(
                "bandit", "/workspace", file_contents={"app.py": "print('x')"}
            )
            mock.assert_called_once()
            # Argument is a temp dir path created by tempfile.mkdtemp
            (called_path,) = mock.call_args[0]
            assert "tron-security-bandit" in called_path

    async def test_routes_to_semgrep(self, security_iso):
        # Same pattern as _routes_to_bandit — file_contents required, temp dir used.
        with patch.object(security_iso, "_run_semgrep", new_callable=AsyncMock,
                         return_value=ToolResult(tool_name="semgrep", exit_code=0,
                                                 stdout="", stderr="", duration_seconds=0)) as mock:
            await security_iso._execute_tool(
                "semgrep", "/workspace", file_contents={"app.py": "print('x')"}
            )
            mock.assert_called_once()
            (called_path,) = mock.call_args[0]
            assert "tron-security-semgrep" in called_path


# ── _run_bandit Tests ────────────────────────────────────────────────


class TestRunBandit:

    async def test_parses_bandit_output(self, security_iso):
        from tron.infra.sandbox.client import ExecutionResult

        bandit_output = json.dumps({
            "results": [
                {
                    "filename": "app.py",
                    "line_number": 12,
                    "test_id": "B608",
                    "issue_text": "Possible SQL injection",
                    "issue_severity": "HIGH",
                    "issue_confidence": "MEDIUM",
                    "code": 'cursor.execute("SELECT...")',
                },
            ],
        })

        # _run_bandit now dispatches through the sandbox client, not
        # asyncio.create_subprocess_exec — mock the sandbox's run_bash.
        mock_sandbox = AsyncMock()
        mock_sandbox.run_bash = AsyncMock(return_value=ExecutionResult(
            stdout=bandit_output, stderr="", exit_code=1,
            duration_seconds=0.1, timed_out=False,
        ))

        with patch.object(security_iso, "_get_sandbox", new_callable=AsyncMock, return_value=mock_sandbox):
            result = await security_iso._run_bandit("/workspace")

        assert result.tool_name == "bandit"
        assert result.findings_count == 1
        assert result.raw_findings[0]["test_id"] == "B608"
        assert result.raw_findings[0]["file"] == "app.py"

    async def test_bandit_no_findings(self, security_iso):
        bandit_output = json.dumps({"results": []})

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(bandit_output.encode(), b""))
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
            result = await security_iso._run_bandit("/workspace")

        assert result.findings_count == 0

    async def test_bandit_invalid_json(self, security_iso):
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"not json", b""))
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
            result = await security_iso._run_bandit("/workspace")

        assert result.findings_count == 0


# ── _run_semgrep Tests ───────────────────────────────────────────────


class TestRunSemgrep:

    async def test_parses_semgrep_output(self, security_iso):
        from tron.infra.sandbox.client import ExecutionResult

        semgrep_output = json.dumps({
            "results": [
                {
                    "path": "app.py",
                    "start": {"line": 15},
                    "check_id": "python.lang.security.audit.exec-detected",
                    "extra": {
                        "message": "Detected exec usage",
                        "severity": "WARNING",
                        "metadata": {},
                    },
                },
            ],
        })

        # Same as _run_bandit: dispatch happens via the sandbox client.
        mock_sandbox = AsyncMock()
        mock_sandbox.run_bash = AsyncMock(return_value=ExecutionResult(
            stdout=semgrep_output, stderr="", exit_code=1,
            duration_seconds=0.1, timed_out=False,
        ))

        with patch.object(security_iso, "_get_sandbox", new_callable=AsyncMock, return_value=mock_sandbox):
            result = await security_iso._run_semgrep("/workspace")

        assert result.tool_name == "semgrep"
        assert result.findings_count == 1
        assert result.raw_findings[0]["file"] == "app.py"
        assert result.raw_findings[0]["line"] == 15

    async def test_semgrep_empty_output(self, security_iso):
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc):
            result = await security_iso._run_semgrep("/workspace")

        assert result.findings_count == 0


# ── _run_safety Tests ────────────────────────────────────────────────


class TestRunSafety:
    """Safety scans Python requirements manifests for known-vulnerable
    versions. The runner is augmentative: missing manifest → silent no-op,
    not an error."""

    async def test_no_manifest_in_scope_is_silent_noop(self, security_iso):
        # No requirements*.txt present in the file set → Safety must NOT
        # invoke the sandbox (waste of time) and must NOT raise. Returns
        # a zero-exit empty ToolResult.
        files = {"src/app.py": "print('hello')", "README.md": "# hi"}

        # If the runner accidentally tried to invoke the sandbox, this would
        # fail because we never patch _get_sandbox.
        result = await security_iso._run_safety("/workspace", files)

        assert result.tool_name == "safety"
        assert result.exit_code == 0
        assert result.findings_count == 0
        assert "no Python requirements manifest" in result.stderr

    async def test_parses_safety_v3_payload(self, security_iso):
        # Safety v3 returns ``{"vulnerabilities": [...]}``.
        from tron.infra.sandbox.client import ExecutionResult

        files = {"requirements.txt": "django==3.2.0\n"}
        v3_payload = json.dumps({
            "vulnerabilities": [
                {
                    "package_name": "django",
                    "analyzed_version": "3.2.0",
                    "vulnerability_id": "GHSA-aaaa-bbbb-cccc",
                    "advisory": "django<4.2 has CVE-2024-XXXX",
                    "CVE": "CVE-2024-XXXX",
                    "more_info_url": "https://example.com",
                },
            ],
        })

        mock_sandbox = AsyncMock()
        mock_sandbox.run_bash = AsyncMock(return_value=ExecutionResult(
            stdout=v3_payload, stderr="", exit_code=64,  # safety exits non-0 when vulns found
            duration_seconds=0.1, timed_out=False,
        ))

        with patch.object(security_iso, "_get_sandbox", new_callable=AsyncMock,
                          return_value=mock_sandbox):
            result = await security_iso._run_safety("/workspace", files)

        assert result.tool_name == "safety"
        assert result.findings_count == 1
        assert result.raw_findings[0]["package"] == "django"
        assert result.raw_findings[0]["vulnerability_id"] == "GHSA-aaaa-bbbb-cccc"
        assert result.raw_findings[0]["cve"] == "CVE-2024-XXXX"

    async def test_parses_safety_v2_legacy_list_payload(self, security_iso):
        # Safety v2 returned a bare JSON list. Both shapes must work so we
        # don't pin to whichever happens to be on the sandbox image today.
        from tron.infra.sandbox.client import ExecutionResult

        files = {"requirements.txt": "flask==1.0\n"}
        v2_payload = json.dumps([
            {
                "package": "flask",
                "installed_version": "1.0",
                "id": "pyup-1234",
                "vulnerable_spec": "<2.0",
                "cve": "",
            },
        ])

        mock_sandbox = AsyncMock()
        mock_sandbox.run_bash = AsyncMock(return_value=ExecutionResult(
            stdout=v2_payload, stderr="", exit_code=64,
            duration_seconds=0.1, timed_out=False,
        ))

        with patch.object(security_iso, "_get_sandbox", new_callable=AsyncMock,
                          return_value=mock_sandbox):
            result = await security_iso._run_safety("/workspace", files)

        assert result.findings_count == 1
        assert result.raw_findings[0]["package"] == "flask"
        assert result.raw_findings[0]["vulnerability_id"] == "pyup-1234"

    async def test_unparseable_output_does_not_raise(self, security_iso):
        # If safety isn't installed in the sandbox image we get a non-JSON
        # stderr blob. The runner must keep the audit going.
        from tron.infra.sandbox.client import ExecutionResult

        files = {"requirements.txt": "django==3.2.0\n"}
        mock_sandbox = AsyncMock()
        mock_sandbox.run_bash = AsyncMock(return_value=ExecutionResult(
            stdout="bash: safety: command not found",
            stderr="exit status 127", exit_code=127,
            duration_seconds=0.0, timed_out=False,
        ))

        with patch.object(security_iso, "_get_sandbox", new_callable=AsyncMock,
                          return_value=mock_sandbox):
            result = await security_iso._run_safety("/workspace", files)

        assert result.tool_name == "safety"
        assert result.findings_count == 0
        # Don't raise — Safety is augmentative, not gating.


# ── _run_eslint Tests ────────────────────────────────────────────────


class TestRunESLint:
    """ESLint with eslint-plugin-security gives JS/TS files a deterministic
    pass to match what Bandit + Semgrep do for Python. Same shape as Safety:
    no-op when nothing to scan, doesn't raise when binary is missing, parses
    JSON into raw_findings."""

    async def test_default_tools_includes_eslint(self):
        assert "eslint" in SecurityISO.DEFAULT_TOOLS

    async def test_no_js_files_in_scope_is_silent_noop(self, security_iso):
        files = {"src/app.py": "print('hi')", "Dockerfile": "FROM python"}

        result = await security_iso._run_eslint("/workspace", files)

        assert result.tool_name == "eslint"
        assert result.exit_code == 0
        assert result.findings_count == 0
        assert "no JS/TS files in scope" in result.stderr

    async def test_parses_eslint_json_findings(self, security_iso):
        from tron.infra.sandbox.client import ExecutionResult

        files = {"src/app.js": "eval(userInput);\n"}
        eslint_output = json.dumps([
            {
                "filePath": "/tmp/tron-security-eslint-abc/src/app.js",
                "messages": [
                    {
                        "ruleId": "security/detect-eval-with-expression",
                        "severity": 2,  # 2 = error
                        "message": "eval can be harmful",
                        "line": 1,
                        "column": 1,
                        "fix": None,
                    },
                    {
                        "ruleId": "security/detect-unsafe-regex",
                        "severity": 2,
                        "message": "Unsafe regex catastrophic backtracking",
                        "line": 5,
                        "column": 10,
                    },
                ],
            },
        ])

        mock_sandbox = AsyncMock()
        mock_sandbox.run_bash = AsyncMock(return_value=ExecutionResult(
            stdout=eslint_output, stderr="", exit_code=1,
            duration_seconds=0.2, timed_out=False,
        ))

        with patch.object(security_iso, "_get_sandbox", new_callable=AsyncMock,
                          return_value=mock_sandbox):
            result = await security_iso._run_eslint(
                "/tmp/tron-security-eslint-abc", files,
            )

        assert result.tool_name == "eslint"
        assert result.findings_count == 2
        # Workspace prefix stripped so confirmation matching against the
        # LLM's reported file_path works ("src/app.js" not the temp path).
        assert result.raw_findings[0]["file"] == "src/app.js"
        assert result.raw_findings[0]["rule_id"] == "security/detect-eval-with-expression"
        assert result.raw_findings[0]["severity"] == 2
        assert result.raw_findings[1]["rule_id"] == "security/detect-unsafe-regex"

    async def test_typescript_files_are_scanned(self, security_iso):
        # The .ts/.tsx extensions count too — closes the gap for TS-heavy
        # projects that previously got LLM-only treatment.
        from tron.infra.sandbox.client import ExecutionResult

        files = {
            "src/auth.ts": "export const x = 1;",
            "components/Login.tsx": "export const C = () => null;",
        }
        mock_sandbox = AsyncMock()
        mock_sandbox.run_bash = AsyncMock(return_value=ExecutionResult(
            stdout="[]", stderr="", exit_code=0,
            duration_seconds=0.1, timed_out=False,
        ))

        with patch.object(security_iso, "_get_sandbox", new_callable=AsyncMock,
                          return_value=mock_sandbox):
            result = await security_iso._run_eslint("/workspace", files)

        # Sandbox WAS called (i.e. files were detected as JS/TS)
        mock_sandbox.run_bash.assert_called_once()
        assert result.findings_count == 0

    async def test_unparseable_output_does_not_raise(self, security_iso):
        from tron.infra.sandbox.client import ExecutionResult

        files = {"src/app.js": "let x = 1;"}
        mock_sandbox = AsyncMock()
        mock_sandbox.run_bash = AsyncMock(return_value=ExecutionResult(
            stdout="bash: eslint: command not found",
            stderr="exit status 127", exit_code=127,
            duration_seconds=0.0, timed_out=False,
        ))

        with patch.object(security_iso, "_get_sandbox", new_callable=AsyncMock,
                          return_value=mock_sandbox):
            result = await security_iso._run_eslint("/workspace", files)

        assert result.tool_name == "eslint"
        assert result.findings_count == 0
        # Don't raise — ESLint is augmentative.
