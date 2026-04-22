"""
Unit tests for Temporal activity handler functions (activities.py).

Tests the actual @activity.defn functions with mocked Temporal context,
database sessions, and external services.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# json is already imported above, no need to re-import

import pytest

from tron.workflows.activities import (
    AuditInput,
    AgentResult,
    FindingInput,
    FixAttempt,
    ScanResult,
    _persist_findings_to_db,
    _finalize_audit_run,
)


def _mock_activity():
    """Patch temporalio activity context (logger, etc.)."""
    return patch("tron.workflows.activities.activity", MagicMock())


def _make_session_factory(mock_session=None):
    """Build an async context manager that mimics _session_factory()."""
    from contextlib import asynccontextmanager

    if mock_session is None:
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.execute = AsyncMock()

    @asynccontextmanager
    async def factory():
        yield mock_session

    return mock_session, factory


# ── load_project_metadata ──


class TestLoadProjectMetadata:

    async def test_loads_project(self):
        from tron.workflows.activities import load_project_metadata

        audit_input = AuditInput(
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
        )

        mock_project = MagicMock()
        mock_project.id = uuid.UUID(audit_input.project_id)
        mock_project.name = "TestProject"
        mock_project.repo_url = "https://github.com/test/repo"
        mock_project.default_branch = "main"

        mock_session, mock_factory = _make_session_factory()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_project
        mock_session.execute = AsyncMock(return_value=mock_result)

        with _mock_activity(), \
             patch("tron.infra.db.session._session_factory", mock_factory):
            result = await load_project_metadata(audit_input)

        assert result.name == "TestProject"
        assert result.repo_url == "https://github.com/test/repo"

    async def test_project_not_found_raises(self):
        from tron.workflows.activities import load_project_metadata

        audit_input = AuditInput(
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
        )

        mock_session, mock_factory = _make_session_factory()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with _mock_activity(), \
             patch("tron.infra.db.session._session_factory", mock_factory):
            with pytest.raises(ValueError, match="not found"):
                await load_project_metadata(audit_input)


# ── scan_repository ──


class TestScanRepository:

    async def test_scan_with_repo_url(self):
        from tron.workflows.activities import scan_repository, ProjectMeta

        meta = ProjectMeta(
            project_id=str(uuid.uuid4()),
            name="Test",
            repo_url="https://github.com/test/repo",
            default_branch="main",
        )

        mock_scanner = AsyncMock()
        mock_scanner.scan = AsyncMock(return_value={"app.py": "print('hello')"})

        mock_session, mock_factory = _make_session_factory()
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)

        with _mock_activity(), \
             patch("tron.services.repo_scanner.RepoScanner", return_value=mock_scanner), \
             patch("tron.services.repo_scanner.detect_languages", return_value=["python"]), \
             patch("tron.infra.db.session._session_factory", mock_factory), \
             patch("tron.services.graph_sync.sync_project_graph", new_callable=AsyncMock), \
             patch("tron.infra.redis.client.get_redis", return_value=mock_redis):
            result = await scan_repository(meta)

        assert result.file_count == 1
        assert "python" in result.languages
        assert result.redis_key.startswith("tron:scan:")
        assert result.file_contents is None
        mock_redis.set.assert_awaited_once()

    async def test_scan_without_repo_url_uses_demo(self):
        from tron.workflows.activities import scan_repository, ProjectMeta

        meta = ProjectMeta(
            project_id=str(uuid.uuid4()),
            name="Test",
            repo_url=None,
            default_branch="main",
        )

        mock_session, mock_factory = _make_session_factory()
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)

        with _mock_activity(), \
             patch("tron.services.repo_scanner.detect_languages", return_value=["python"]), \
             patch("tron.infra.db.session._session_factory", mock_factory), \
             patch("tron.services.graph_sync.sync_project_graph", new_callable=AsyncMock), \
             patch("tron.infra.redis.client.get_redis", return_value=mock_redis):
            result = await scan_repository(meta)

        assert result.file_count >= 1
        assert result.redis_key.startswith("tron:scan:")
        stored = json.loads(mock_redis.set.call_args[0][1])
        assert "app.py" in stored

    async def test_scan_error_propagates(self):
        from tron.workflows.activities import scan_repository, ProjectMeta
        from tron.services.repo_scanner import RepoScanError

        meta = ProjectMeta(
            project_id=str(uuid.uuid4()),
            name="Test",
            repo_url="https://github.com/bad/repo",
            default_branch="main",
        )

        mock_scanner = AsyncMock()
        mock_scanner.scan = AsyncMock(side_effect=RepoScanError("clone failed"))

        mock_session, mock_factory = _make_session_factory()
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)

        with _mock_activity(), \
             patch("tron.services.repo_scanner.RepoScanner", return_value=mock_scanner), \
             patch("tron.services.repo_scanner.detect_languages", return_value=["python"]), \
             patch("tron.infra.db.session._session_factory", mock_factory), \
             patch("tron.services.graph_sync.sync_project_graph", new_callable=AsyncMock), \
             patch("tron.infra.redis.client.get_redis", return_value=mock_redis):
            with pytest.raises(RepoScanError, match="clone failed"):
                await scan_repository(meta)


# ── verify_fix ──


class TestVerifyFix:

    async def test_empty_code_fails(self):
        from tron.workflows.activities import verify_fix

        finding = FindingInput(
            finding_id=str(uuid.uuid4()),
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            file_path="app.py", line_number=10,
            vulnerability_type="sql_injection",
            severity="high", description="SQL injection",
            code_snippet="bad code",
        )
        attempt = FixAttempt(iteration=1, fix_code="", verification_passed=False, verification_output="")

        with _mock_activity():
            result = await verify_fix(finding, attempt)

        assert not result.verification_passed
        assert "No fix code" in result.verification_output

    async def test_sql_injection_still_vulnerable(self):
        from tron.workflows.activities import verify_fix

        finding = FindingInput(
            finding_id=str(uuid.uuid4()),
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            file_path="app.py", line_number=10,
            vulnerability_type="sql_injection",
            severity="high", description="SQL injection",
            code_snippet="bad code",
        )
        bad_fix = 'cursor.execute("SELECT * FROM users WHERE name = \'" + user + "\'")'
        attempt = FixAttempt(iteration=1, fix_code=bad_fix, verification_passed=False, verification_output="")

        with _mock_activity():
            result = await verify_fix(finding, attempt)

        assert not result.verification_passed

    async def test_sql_injection_fixed(self):
        from tron.workflows.activities import verify_fix

        finding = FindingInput(
            finding_id=str(uuid.uuid4()),
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            file_path="app.py", line_number=10,
            vulnerability_type="sql_injection",
            severity="high", description="SQL injection",
            code_snippet="bad code",
        )
        good_fix = 'cursor.execute("SELECT * FROM users WHERE name = ?", (user,))'
        attempt = FixAttempt(iteration=1, fix_code=good_fix, verification_passed=False, verification_output="")

        with _mock_activity():
            result = await verify_fix(finding, attempt)

        assert result.verification_passed

    async def test_command_injection_detected(self):
        from tron.workflows.activities import verify_fix

        finding = FindingInput(
            finding_id=str(uuid.uuid4()),
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            file_path="app.py", line_number=10,
            vulnerability_type="command_injection",
            severity="critical", description="Command injection",
            code_snippet="bad code",
        )
        bad_fix = 'subprocess.Popen(cmd, shell=True)'
        attempt = FixAttempt(iteration=1, fix_code=bad_fix, verification_passed=False, verification_output="")

        with _mock_activity():
            result = await verify_fix(finding, attempt)

        assert not result.verification_passed

    async def test_pickle_deserialization_detected(self):
        from tron.workflows.activities import verify_fix

        finding = FindingInput(
            finding_id=str(uuid.uuid4()),
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            file_path="app.py", line_number=10,
            vulnerability_type="insecure_deserialization",
            severity="high", description="Insecure deserialization",
            code_snippet="bad code",
        )
        bad_fix = 'obj = pickle.loads(data)'
        attempt = FixAttempt(iteration=1, fix_code=bad_fix, verification_passed=False, verification_output="")

        with _mock_activity():
            result = await verify_fix(finding, attempt)

        assert not result.verification_passed

    async def test_xss_detected(self):
        from tron.workflows.activities import verify_fix

        finding = FindingInput(
            finding_id=str(uuid.uuid4()),
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            file_path="app.py", line_number=10,
            vulnerability_type="xss",
            severity="medium", description="XSS",
            code_snippet="bad code",
        )
        bad_fix = 'return render_template_string("<h1>" + name + "</h1>")'
        attempt = FixAttempt(iteration=1, fix_code=bad_fix, verification_passed=False, verification_output="")

        with _mock_activity():
            result = await verify_fix(finding, attempt)

        assert not result.verification_passed

    async def test_hardcoded_secret_detected(self):
        from tron.workflows.activities import verify_fix

        finding = FindingInput(
            finding_id=str(uuid.uuid4()),
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            file_path="app.py", line_number=10,
            vulnerability_type="hardcoded_secrets",
            severity="high", description="Hardcoded secret",
            code_snippet="bad code",
        )
        bad_fix = 'PASSWORD = "mysecret123"'
        attempt = FixAttempt(iteration=1, fix_code=bad_fix, verification_passed=False, verification_output="")

        with _mock_activity():
            result = await verify_fix(finding, attempt)

        assert not result.verification_passed

    async def test_unknown_vuln_type_passes(self):
        from tron.workflows.activities import verify_fix

        finding = FindingInput(
            finding_id=str(uuid.uuid4()),
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            file_path="app.py", line_number=10,
            vulnerability_type="unknown_type",
            severity="low", description="Unknown",
            code_snippet="bad code",
        )
        attempt = FixAttempt(iteration=1, fix_code="some fix code", verification_passed=False, verification_output="")

        with _mock_activity():
            result = await verify_fix(finding, attempt)

        assert result.verification_passed


# ── persist_fix ──


class TestPersistFix:

    async def test_persists_to_db(self):
        from tron.workflows.activities import persist_fix

        finding = FindingInput(
            finding_id=str(uuid.uuid4()),
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            file_path="app.py", line_number=10,
            vulnerability_type="sql_injection",
            severity="high", description="SQL injection",
            code_snippet="bad code",
        )
        attempt = FixAttempt(
            iteration=1, fix_code="fixed code",
            verification_passed=True, verification_output="PASS",
        )

        mock_session, mock_factory = _make_session_factory()

        with _mock_activity(), \
             patch("tron.infra.db.session._session_factory", mock_factory):
            result = await persist_fix(finding, attempt)

        assert result == finding.finding_id
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()


# ── escalate_to_human ──


class TestEscalateToHuman:

    async def test_escalates(self):
        from tron.workflows.activities import escalate_to_human

        finding = FindingInput(
            finding_id=str(uuid.uuid4()),
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            file_path="app.py", line_number=10,
            vulnerability_type="sql_injection",
            severity="high", description="SQL injection",
            code_snippet="bad code",
        )

        mock_session, mock_factory = _make_session_factory()

        with _mock_activity(), \
             patch("tron.infra.db.session._session_factory", mock_factory):
            result = await escalate_to_human(finding, 3)

        assert "Escalated" in result
        assert "3 attempts" in result
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()


# ── _persist_findings_to_db ──


class TestPersistFindingsToDb:

    async def test_empty_findings_noop(self):
        audit_input = AuditInput(
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
        )

        with _mock_activity():
            await _persist_findings_to_db(audit_input, [])

    async def test_persists_findings(self):
        audit_input = AuditInput(
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
        )
        findings = [
            {
                "finding_fingerprint": "fp1",
                "vulnerability_type": "sql_injection",
                "file_path": "app.py",
                "line_number": 10,
                "severity": "high",
                "description": "SQL injection vulnerability",
                "code_snippet": "bad code",
            },
            {
                "finding_fingerprint": "fp2",
                "vulnerability_type": "xss",
                "file_path": "web.py",
                "line_number": 20,
                "severity": "medium",
                "description": "XSS vulnerability",
            },
        ]

        mock_session, mock_factory = _make_session_factory()

        with _mock_activity(), \
             patch("tron.infra.db.session._session_factory", mock_factory):
            await _persist_findings_to_db(audit_input, findings)

        assert mock_session.add.call_count == 2
        mock_session.commit.assert_called_once()


# ── _finalize_audit_run ──


class TestFinalizeAuditRun:

    async def test_updates_audit_run(self):
        audit_input = AuditInput(
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
        )
        findings = [{"severity": "high"}, {"severity": "medium"}]
        sev_counts = {"critical": 0, "high": 1, "medium": 1, "low": 0}

        mock_session, mock_factory = _make_session_factory()

        with _mock_activity(), \
             patch("tron.infra.db.session._session_factory", mock_factory):
            await _finalize_audit_run(audit_input, findings, sev_counts, 5.0)

        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()


# ── generate_fix ──


class TestGenerateFix:

    async def test_generates_fix_code(self):
        from tron.workflows.activities import generate_fix

        finding = FindingInput(
            finding_id=str(uuid.uuid4()),
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            file_path="app.py", line_number=10,
            vulnerability_type="sql_injection",
            severity="high", description="SQL injection",
            code_snippet="cursor.execute(q + user)",
        )

        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "cursor.execute('SELECT * FROM t WHERE id = ?', (user,))"
        mock_llm.complete = AsyncMock(return_value=mock_response)
        mock_llm.close = AsyncMock()

        with _mock_activity(), \
             patch("tron.workflows._worker_state.get_worker_secrets", return_value={"llm/anthropic-key": "key"}), \
             patch("tron.infra.llm.client.LLMClient", return_value=mock_llm):
            result = await generate_fix(finding, 1)

        assert result.fix_code != ""
        assert result.iteration == 1

    async def test_generate_fix_strips_markdown(self):
        from tron.workflows.activities import generate_fix

        finding = FindingInput(
            finding_id=str(uuid.uuid4()),
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            file_path="app.py", line_number=10,
            vulnerability_type="sql_injection",
            severity="high", description="SQL injection",
            code_snippet="bad",
        )

        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "```python\nfixed_code()\n```"
        mock_llm.complete = AsyncMock(return_value=mock_response)
        mock_llm.close = AsyncMock()

        with _mock_activity(), \
             patch("tron.workflows._worker_state.get_worker_secrets", return_value={}), \
             patch("tron.infra.llm.client.LLMClient", return_value=mock_llm):
            result = await generate_fix(finding, 1)

        assert "```" not in result.fix_code

    async def test_generate_fix_retry_prompt(self):
        from tron.workflows.activities import generate_fix

        finding = FindingInput(
            finding_id=str(uuid.uuid4()),
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            file_path="app.py", line_number=10,
            vulnerability_type="xss",
            severity="medium", description="XSS",
            code_snippet="bad",
        )

        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "escape(user_input)"
        mock_llm.complete = AsyncMock(return_value=mock_response)
        mock_llm.close = AsyncMock()

        with _mock_activity(), \
             patch("tron.workflows._worker_state.get_worker_secrets", return_value={}), \
             patch("tron.infra.llm.client.LLMClient", return_value=mock_llm):
            result = await generate_fix(finding, 3)

        assert result.iteration == 3

    async def test_generate_fix_llm_error(self):
        from tron.workflows.activities import generate_fix

        finding = FindingInput(
            finding_id=str(uuid.uuid4()),
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            file_path="app.py", line_number=10,
            vulnerability_type="xss",
            severity="medium", description="XSS",
            code_snippet="bad",
        )

        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(side_effect=RuntimeError("LLM timeout"))
        mock_llm.close = AsyncMock()

        with _mock_activity(), \
             patch("tron.workflows._worker_state.get_worker_secrets", return_value={}), \
             patch("tron.infra.llm.client.LLMClient", return_value=mock_llm):
            result = await generate_fix(finding, 1)

        assert result.fix_code == ""
        assert result.error_message == "LLM timeout"


# ── run_security_agent, run_builder_agent, run_performance_agent ──


class TestRunAgentDelegation:
    """Test that the three agent wrapper functions delegate to _run_agent."""

    async def test_run_security_agent_delegates(self):
        from tron.workflows.activities import run_security_agent

        audit_input = AuditInput(
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
        )
        scan_result = ScanResult(
            file_count=1,
            total_size_kb=10.0,
            languages=["python"],
            file_contents={"app.py": "code"},
        )

        mock_agent_result = AgentResult(
            agent_id="security-iso-primary",
            specialization="security",
            findings_count=2,
            findings_json="[]",
            duration_seconds=1.0,
            llm_tokens_used=100,
            llm_cost_usd=0.01,
            errors=[],
        )

        with _mock_activity(), \
             patch("tron.workflows.activities._run_agent", new_callable=AsyncMock, return_value=mock_agent_result):
            result = await run_security_agent(audit_input, scan_result)

        assert result.specialization == "security"
        assert result.agent_id == "security-iso-primary"

    async def test_run_builder_agent_delegates(self):
        from tron.workflows.activities import run_builder_agent

        audit_input = AuditInput(
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
        )
        scan_result = ScanResult(
            file_count=1,
            total_size_kb=10.0,
            languages=["python"],
            file_contents={"app.py": "code"},
        )

        mock_agent_result = AgentResult(
            agent_id="builder-iso-primary",
            specialization="builder",
            findings_count=1,
            findings_json="[]",
            duration_seconds=2.0,
            llm_tokens_used=200,
            llm_cost_usd=0.02,
            errors=[],
        )

        with _mock_activity(), \
             patch("tron.workflows.activities._run_agent", new_callable=AsyncMock, return_value=mock_agent_result):
            result = await run_builder_agent(audit_input, scan_result)

        assert result.specialization == "builder"
        assert result.agent_id == "builder-iso-primary"

    async def test_run_performance_agent_delegates(self):
        from tron.workflows.activities import run_performance_agent

        audit_input = AuditInput(
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
        )
        scan_result = ScanResult(
            file_count=1,
            total_size_kb=10.0,
            languages=["python"],
            file_contents={"app.py": "code"},
        )

        mock_agent_result = AgentResult(
            agent_id="performance-iso-primary",
            specialization="performance",
            findings_count=3,
            findings_json="[]",
            duration_seconds=1.5,
            llm_tokens_used=150,
            llm_cost_usd=0.015,
            errors=[],
        )

        with _mock_activity(), \
             patch("tron.workflows.activities._run_agent", new_callable=AsyncMock, return_value=mock_agent_result):
            result = await run_performance_agent(audit_input, scan_result)

        assert result.specialization == "performance"
        assert result.agent_id == "performance-iso-primary"


# ── _run_agent ──


class TestRunAgent:
    """Test the core _run_agent function."""

    async def test_run_agent_success_path(self):
        from tron.workflows.activities import _run_agent

        audit_input = AuditInput(
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
        )
        scan_result = ScanResult(
            file_count=1,
            total_size_kb=10.0,
            languages=["python"],
            file_contents={"app.py": "code"},
        )

        # Mock the agent class
        mock_agent = AsyncMock()
        mock_findings = [MagicMock()]
        mock_findings[0].model_dump = MagicMock(return_value={"id": str(uuid.uuid4())})
        mock_batch = MagicMock()
        mock_batch.findings = mock_findings
        mock_agent.execute = AsyncMock(return_value=mock_batch)
        mock_agent.metrics = MagicMock()
        mock_agent.metrics.llm_tokens_used = 100
        mock_agent.metrics.llm_cost_usd = 0.01
        mock_agent.metrics.errors = []

        mock_llm = AsyncMock()
        mock_llm.close = AsyncMock()

        with _mock_activity(), \
             patch("tron.workflows._worker_state.get_worker_secrets", return_value={"llm/anthropic-key": "key"}), \
             patch("tron.infra.llm.client.LLMClient", return_value=mock_llm), \
             patch("tron.agents.security_iso.SecurityISO", return_value=mock_agent), \
             patch("tron.infra.redis.pubsub.publish_audit_event", new_callable=AsyncMock):

            result = await _run_agent(
                audit_input=audit_input,
                scan_result=scan_result,
                specialization="security",
                agent_id="test-agent",
            )

        assert result.agent_id == "test-agent"
        assert result.specialization == "security"
        assert result.findings_count == 1
        assert result.llm_tokens_used == 100

    async def test_run_agent_unknown_specialization(self):
        from tron.workflows.activities import _run_agent

        audit_input = AuditInput(
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
        )
        scan_result = ScanResult(
            file_count=1,
            total_size_kb=10.0,
            languages=["python"],
            file_contents={"app.py": "code"},
        )

        mock_llm = AsyncMock()
        mock_llm.close = AsyncMock()

        with _mock_activity(), \
             patch("tron.workflows._worker_state.get_worker_secrets", return_value={"llm/anthropic-key": "key"}), \
             patch("tron.infra.llm.client.LLMClient", return_value=mock_llm), \
             patch("tron.infra.redis.pubsub.publish_audit_event", new_callable=AsyncMock):

            # ISOSpecialization("unknown_spec") raises ValueError before the try block
            with pytest.raises(ValueError, match="unknown_spec"):
                await _run_agent(
                    audit_input=audit_input,
                    scan_result=scan_result,
                    specialization="unknown_spec",
                    agent_id="test-agent",
                )

    async def test_run_agent_exception_handling(self):
        from tron.workflows.activities import _run_agent

        audit_input = AuditInput(
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
        )
        scan_result = ScanResult(
            file_count=1,
            total_size_kb=10.0,
            languages=["python"],
            file_contents={"app.py": "code"},
        )

        # Mock the agent to raise an exception
        mock_agent = AsyncMock()
        mock_agent.execute = AsyncMock(side_effect=RuntimeError("Agent failed"))

        mock_llm = AsyncMock()
        mock_llm.close = AsyncMock()

        with _mock_activity(), \
             patch("tron.workflows._worker_state.get_worker_secrets", return_value={"llm/anthropic-key": "key"}), \
             patch("tron.infra.llm.client.LLMClient", return_value=mock_llm), \
             patch("tron.agents.security_iso.SecurityISO", return_value=mock_agent), \
             patch("tron.infra.redis.pubsub.publish_audit_event", new_callable=AsyncMock):

            result = await _run_agent(
                audit_input=audit_input,
                scan_result=scan_result,
                specialization="security",
                agent_id="test-agent",
            )

        assert result.findings_count == 0
        assert len(result.errors) > 0
        assert "Agent failed" in result.errors[0]

    async def test_run_agent_openai_fallback(self):
        from tron.workflows.activities import _run_agent

        audit_input = AuditInput(
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
        )
        scan_result = ScanResult(
            file_count=1,
            total_size_kb=10.0,
            languages=["python"],
            file_contents={"app.py": "code"},
        )

        mock_agent = AsyncMock()
        mock_batch = MagicMock()
        mock_batch.findings = []
        mock_agent.execute = AsyncMock(return_value=mock_batch)
        mock_agent.metrics = MagicMock()
        mock_agent.metrics.llm_tokens_used = 0
        mock_agent.metrics.llm_cost_usd = 0.0
        mock_agent.metrics.errors = []

        mock_llm = AsyncMock()
        mock_llm.close = AsyncMock()

        with _mock_activity(), \
             patch("tron.workflows._worker_state.get_worker_secrets", return_value={"llm/openai-key": "openai-key"}), \
             patch("tron.infra.llm.client.LLMClient", return_value=mock_llm), \
             patch("tron.agents.builder_iso.BuilderISO", return_value=mock_agent), \
             patch("tron.infra.redis.pubsub.publish_audit_event", new_callable=AsyncMock):

            result = await _run_agent(
                audit_input=audit_input,
                scan_result=scan_result,
                specialization="builder",
                agent_id="test-agent",
            )

        assert result.agent_id == "test-agent"


# ── synthesize_findings ──


class TestSynthesizeFindings:
    """Test the synthesize_findings activity."""

    async def test_synthesize_findings_deduplicates(self):
        from tron.workflows.activities import synthesize_findings

        audit_input = AuditInput(
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
        )

        agent_results = [
            AgentResult(
                agent_id="agent1",
                specialization="security",
                findings_count=2,
                findings_json=json.dumps([
                    {
                        "finding_fingerprint": "fp1",
                        "vulnerability_type": "sql_injection",
                        "severity": "critical",
                        "confidence": 0.9,
                        "file_path": "app.py",
                        "line_number": 10,
                    },
                    {
                        "finding_fingerprint": "fp2",
                        "vulnerability_type": "hardcoded_secrets",
                        "severity": "high",
                        "confidence": 0.8,
                        "file_path": "app.py",
                        "line_number": 5,
                    },
                ]),
                duration_seconds=1.0,
                llm_tokens_used=100,
                llm_cost_usd=0.01,
                errors=[],
            ),
            AgentResult(
                agent_id="agent2",
                specialization="builder",
                findings_count=1,
                findings_json=json.dumps([
                    {
                        "finding_fingerprint": "fp1",
                        "vulnerability_type": "sql_injection",
                        "severity": "critical",
                        "confidence": 0.85,
                        "file_path": "app.py",
                        "line_number": 10,
                    },
                ]),
                duration_seconds=1.5,
                llm_tokens_used=150,
                llm_cost_usd=0.015,
                errors=[],
            ),
        ]

        mock_session, mock_factory = _make_session_factory()

        with _mock_activity(), \
             patch("tron.infra.redis.pubsub.publish_progress", new_callable=AsyncMock), \
             patch("tron.infra.redis.pubsub.publish_audit_completed", new_callable=AsyncMock), \
             patch("tron.infra.db.session._session_factory", mock_factory), \
             patch("tron.workflows.activities._persist_findings_to_db", new_callable=AsyncMock), \
             patch("tron.workflows.activities._finalize_audit_run", new_callable=AsyncMock):

            result = await synthesize_findings(audit_input, agent_results)

        assert result.audit_run_id == audit_input.audit_run_id
        assert result.findings_total == 2  # Two unique fingerprints
        assert result.findings_critical == 1
        assert result.findings_high == 1
        assert result.agents_run == 2

    async def test_synthesize_findings_invalid_json(self):
        from tron.workflows.activities import synthesize_findings

        audit_input = AuditInput(
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
        )

        agent_results = [
            AgentResult(
                agent_id="agent1",
                specialization="security",
                findings_count=0,
                findings_json="invalid json",
                duration_seconds=1.0,
                llm_tokens_used=0,
                llm_cost_usd=0.0,
                errors=[],
            ),
        ]

        mock_session, mock_factory = _make_session_factory()

        with _mock_activity(), \
             patch("tron.infra.redis.pubsub.publish_progress", new_callable=AsyncMock), \
             patch("tron.infra.redis.pubsub.publish_audit_completed", new_callable=AsyncMock), \
             patch("tron.infra.db.session._session_factory", mock_factory), \
             patch("tron.workflows.activities._persist_findings_to_db", new_callable=AsyncMock), \
             patch("tron.workflows.activities._finalize_audit_run", new_callable=AsyncMock):

            result = await synthesize_findings(audit_input, agent_results)

        assert result.findings_total == 0

    async def test_synthesize_findings_tool_confirmed_precedence(self):
        from tron.workflows.activities import synthesize_findings

        audit_input = AuditInput(
            audit_run_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
        )

        agent_results = [
            AgentResult(
                agent_id="agent1",
                specialization="security",
                findings_count=1,
                findings_json=json.dumps([
                    {
                        "finding_fingerprint": "fp1",
                        "vulnerability_type": "sql_injection",
                        "severity": "medium",
                        "confidence": 0.95,
                        "deterministic_tool_confirmed": False,
                        "file_path": "app.py",
                        "line_number": 10,
                    },
                ]),
                duration_seconds=1.0,
                llm_tokens_used=100,
                llm_cost_usd=0.01,
                errors=[],
            ),
            AgentResult(
                agent_id="agent2",
                specialization="builder",
                findings_count=1,
                findings_json=json.dumps([
                    {
                        "finding_fingerprint": "fp1",
                        "vulnerability_type": "sql_injection",
                        "severity": "low",
                        "confidence": 0.85,
                        "deterministic_tool_confirmed": True,
                        "file_path": "app.py",
                        "line_number": 10,
                    },
                ]),
                duration_seconds=1.0,
                llm_tokens_used=100,
                llm_cost_usd=0.01,
                errors=[],
            ),
        ]

        mock_session, mock_factory = _make_session_factory()

        with _mock_activity(), \
             patch("tron.infra.redis.pubsub.publish_progress", new_callable=AsyncMock), \
             patch("tron.infra.redis.pubsub.publish_audit_completed", new_callable=AsyncMock), \
             patch("tron.infra.db.session._session_factory", mock_factory), \
             patch("tron.workflows.activities._persist_findings_to_db", new_callable=AsyncMock), \
             patch("tron.workflows.activities._finalize_audit_run", new_callable=AsyncMock):

            result = await synthesize_findings(audit_input, agent_results)

        assert result.findings_total == 1
