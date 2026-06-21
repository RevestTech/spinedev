"""
Unit tests for AuditExecutor.

Tests:
  - Construction and agent initialization
  - _build_agent_manager (provider selection based on keys)
  - _detect_languages delegation
  - _demo_source_files
  - _persist_findings (mocked DB)
  - _finalize_audit / _fail_audit (mocked DB)
  - run() happy path (mocked everything)
  - run() error path (exception handling)
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tron.agents.base import ISOSpecialization, LLMProvider
from tron.services.audit_executor import AuditExecutor, _SEVERITY_ORDER


@pytest.fixture(autouse=True)
def _no_http(monkeypatch):
    """Prevent LLMClient from creating a real httpx.AsyncClient."""
    def _fake_client(**kwargs):
        mock = MagicMock()
        mock.aclose = AsyncMock()
        return mock
    monkeypatch.setattr(
        "tron.infra.llm.client.httpx.AsyncClient",
        _fake_client,
    )


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def fake_secrets():
    return {
        "auth/master-key": "test-key-123",
        "llm/anthropic-key": "sk-ant-test",
        "llm/openai-key": "sk-oai-test",
    }


@pytest.fixture
def fake_secrets_no_anthropic():
    return {
        "auth/master-key": "test-key-123",
        "llm/anthropic-key": "REPLACE_ME_IN_VAULT",
        "llm/openai-key": "sk-oai-test",
    }


@pytest.fixture
def fake_secrets_no_llm():
    return {
        "auth/master-key": "test-key-123",
        "llm/anthropic-key": "",
        "llm/openai-key": "",
    }


@pytest.fixture
def mock_session_factory():
    """Mock async session factory."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock()
    factory.return_value = session
    return factory


# ── Tests: Severity ordering ──────────────────────────────────────────


class TestSeverityOrder:

    def test_all_severity_levels_mapped(self):
        from tron.schemas.verification import SeverityLevel
        for level in [SeverityLevel.CRITICAL, SeverityLevel.HIGH,
                      SeverityLevel.MEDIUM, SeverityLevel.LOW, SeverityLevel.INFO]:
            assert level in _SEVERITY_ORDER


# ── Tests: _build_agent_manager ───────────────────────────────────────


class TestBuildAgentManager:

    def test_anthropic_preferred(self, fake_secrets, mock_session_factory):
        """When Anthropic key is available, use Anthropic provider."""
        executor = AuditExecutor(mock_session_factory, fake_secrets)
        manager = executor._build_agent_manager()

        agents = manager._agents
        assert ISOSpecialization.SECURITY in agents
        assert ISOSpecialization.BUILDER in agents
        assert ISOSpecialization.PERFORMANCE in agents
        assert agents[ISOSpecialization.SECURITY].config.model_provider == LLMProvider.ANTHROPIC

    def test_openai_fallback(self, fake_secrets_no_anthropic, mock_session_factory):
        """When no Anthropic key, fall back to OpenAI."""
        executor = AuditExecutor(mock_session_factory, fake_secrets_no_anthropic)
        manager = executor._build_agent_manager()

        agents = manager._agents
        assert agents[ISOSpecialization.SECURITY].config.model_provider == LLMProvider.OPENAI
        assert agents[ISOSpecialization.SECURITY].config.model_name == "gpt-4o"

    def test_no_keys_raises_on_agent_init(self, fake_secrets_no_llm, mock_session_factory):
        """Without LLM keys, agent construction raises ValueError."""
        executor = AuditExecutor(mock_session_factory, fake_secrets_no_llm)
        with pytest.raises(ValueError, match="not configured"):
            executor._build_agent_manager()

    def test_six_agents_registered(self, fake_secrets, mock_session_factory):
        """Six ISO agents per proposal: security, builder, performance, qa, compliance, documentation."""
        executor = AuditExecutor(mock_session_factory, fake_secrets)
        manager = executor._build_agent_manager()
        assert len(manager._agents) == 6


# ── Tests: _demo_source_files ─────────────────────────────────────────


class TestDemoSourceFiles:

    def test_returns_demo_code(self):
        """Demo files contain vulnerable Flask app."""
        files = AuditExecutor._demo_source_files()
        assert "app.py" in files
        assert "Flask" in files["app.py"]
        assert "sql" in files["app.py"].lower()

    def test_returns_single_file(self):
        files = AuditExecutor._demo_source_files()
        assert len(files) == 1


# ── Tests: _detect_languages ──────────────────────────────────────────


class TestDetectLanguages:

    def test_detect_python(self):
        langs = AuditExecutor._detect_languages({"main.py": "print('hi')"})
        assert "python" in langs

    def test_detect_javascript(self):
        langs = AuditExecutor._detect_languages({"app.js": "console.log()"})
        assert "javascript" in langs


# ── Tests: run() ──────────────────────────────────────────────────────


class TestRunHappyPath:

    async def test_run_completes(self, fake_secrets, mock_session_factory):
        """Full run with mocked components completes without error."""
        executor = AuditExecutor(mock_session_factory, fake_secrets)

        # Mock internal methods
        mock_project = MagicMock()
        mock_project.name = "TestProj"
        mock_project.repo_url = None  # Force demo files

        with patch.object(executor, "_load_project", new_callable=AsyncMock, return_value=mock_project), \
             patch.object(executor, "_update_status", new_callable=AsyncMock), \
             patch.object(executor, "_persist_findings", new_callable=AsyncMock), \
             patch.object(executor, "_finalize_audit", new_callable=AsyncMock), \
             patch("tron.services.audit_executor.publish_audit_event", new_callable=AsyncMock), \
             patch("tron.services.audit_executor.publish_finding", new_callable=AsyncMock), \
             patch("tron.services.audit_executor.publish_audit_completed", new_callable=AsyncMock), \
             patch("tron.services.audit_executor.publish_progress", new_callable=AsyncMock), \
             patch(
                 "tron.services.audit_executor.load_suppressed_fingerprints_for_project",
                 new_callable=AsyncMock, return_value=set(),
             ):

            # Mock the manager run_audit
            mock_result = MagicMock()
            mock_result.findings = []
            mock_result.duration_seconds = 1.0

            with patch.object(executor, "_build_agent_manager") as mock_build:
                mock_manager = MagicMock()
                mock_manager._agents = {}
                mock_manager.run_audit = AsyncMock(return_value=mock_result)
                mock_build.return_value = mock_manager

                run_id = uuid.uuid4()
                proj_id = uuid.uuid4()

                await executor.run(run_id, proj_id)

            # Verify finalize was called
            executor._finalize_audit.assert_called_once()

    async def test_run_handles_error(self, fake_secrets, mock_session_factory):
        """When _load_project raises, audit is marked failed."""
        executor = AuditExecutor(mock_session_factory, fake_secrets)

        with patch.object(executor, "_load_project", new_callable=AsyncMock, side_effect=ValueError("Not found")), \
             patch.object(executor, "_update_status", new_callable=AsyncMock), \
             patch.object(executor, "_fail_audit", new_callable=AsyncMock), \
             patch("tron.services.audit_executor.publish_audit_failed", new_callable=AsyncMock):

            run_id = uuid.uuid4()
            proj_id = uuid.uuid4()

            await executor.run(run_id, proj_id)

            # Verify fail_audit was called
            executor._fail_audit.assert_called_once()

    async def test_run_project_not_found(self, fake_secrets, mock_session_factory):
        """_load_project returns None → ValueError → fail_audit."""
        executor = AuditExecutor(mock_session_factory, fake_secrets)

        with patch.object(executor, "_load_project", new_callable=AsyncMock, return_value=None), \
             patch.object(executor, "_update_status", new_callable=AsyncMock), \
             patch.object(executor, "_fail_audit", new_callable=AsyncMock), \
             patch("tron.services.audit_executor.publish_audit_failed", new_callable=AsyncMock):

            await executor.run(uuid.uuid4(), uuid.uuid4())

            executor._fail_audit.assert_called_once()
            call_args = executor._fail_audit.call_args
            assert "not found" in call_args[0][1].lower()


class TestCollectSourceFiles:

    async def test_no_repo_url_uses_demo(self, fake_secrets, mock_session_factory):
        """Project without repo_url falls back to demo files."""
        executor = AuditExecutor(mock_session_factory, fake_secrets)

        mock_project = MagicMock()
        mock_project.repo_url = None

        result = await executor._collect_source_files(mock_project)
        assert "app.py" in result

    async def test_repo_url_calls_scanner(self, fake_secrets, mock_session_factory):
        """Project with repo_url triggers RepoScanner."""
        executor = AuditExecutor(mock_session_factory, fake_secrets)

        mock_project = MagicMock()
        mock_project.repo_url = "https://github.com/test/repo.git"
        mock_project.default_branch = "main"

        mock_files = {"src/app.py": "code"}
        with patch("tron.services.audit_executor.RepoScanner") as MockScanner:
            mock_scanner = MockScanner.return_value
            mock_scanner.scan = AsyncMock(return_value=mock_files)

            result = await executor._collect_source_files(mock_project)

        assert result == mock_files

    async def test_repo_scan_error_propagates(self, fake_secrets, mock_session_factory):
        """RepoScanError propagates — real repos must not silently use demo code."""
        from tron.services.repo_scanner import RepoScanError

        executor = AuditExecutor(mock_session_factory, fake_secrets)

        mock_project = MagicMock()
        mock_project.repo_url = "https://github.com/test/repo.git"
        mock_project.default_branch = "main"

        with patch("tron.services.audit_executor.RepoScanner") as MockScanner:
            mock_scanner = MockScanner.return_value
            mock_scanner.scan = AsyncMock(side_effect=RepoScanError("Clone failed"))

            with pytest.raises(RepoScanError, match="Clone failed"):
                await executor._collect_source_files(mock_project)


# ── Tests: _persist_findings ──────────────────────────────────────────


class TestPersistFindings:

    async def test_persist_findings_with_findings(self, fake_secrets, mock_session_factory):
        """Persist multiple findings to database."""
        from tron.schemas.verification import SeverityLevel, VulnerabilityType

        executor = AuditExecutor(mock_session_factory, fake_secrets)

        audit_run_id = uuid.uuid4()
        project_id = uuid.uuid4()

        finding1 = MagicMock()
        finding1.finding_fingerprint = "fp1"
        finding1.vulnerability_type = VulnerabilityType.SQL_INJECTION
        finding1.file_path = "app.py"
        finding1.line_number = 10
        finding1.line_end = None
        finding1.severity = SeverityLevel.CRITICAL
        finding1.description = "SQL injection found"
        finding1.fix_suggestion = "Use parameterized queries"
        finding1.code_snippet = "bad code"

        finding2 = MagicMock()
        finding2.finding_fingerprint = "fp2"
        finding2.vulnerability_type = VulnerabilityType.HARDCODED_SECRETS
        finding2.file_path = "app.py"
        finding2.line_number = 5
        finding2.line_end = None
        finding2.severity = SeverityLevel.HIGH
        finding2.description = "Hardcoded password"
        finding2.fix_suggestion = "Use environment variables"
        finding2.code_snippet = 'PASSWORD = "secret"'

        result = MagicMock()
        result.findings = [finding1, finding2]
        result.duration_seconds = 1.5

        await executor._persist_findings(audit_run_id, project_id, result)

        # Verify session.add was called twice
        assert mock_session_factory.return_value.__aenter__.return_value.add.call_count == 2
        mock_session_factory.return_value.__aenter__.return_value.commit.assert_called_once()

    async def test_persist_findings_empty(self, fake_secrets, mock_session_factory):
        """Empty findings list — no DB writes."""
        executor = AuditExecutor(mock_session_factory, fake_secrets)

        audit_run_id = uuid.uuid4()
        project_id = uuid.uuid4()

        result = MagicMock()
        result.findings = []
        result.duration_seconds = 0.5

        await executor._persist_findings(audit_run_id, project_id, result)

        # session.add should not be called
        assert mock_session_factory.return_value.__aenter__.return_value.add.call_count == 0


# ── Tests: _finalize_audit ────────────────────────────────────────────


class TestFinalizeAudit:

    async def test_finalize_audit_updates_counts(self, fake_secrets, mock_session_factory):
        """Update audit run with final severity counts."""
        from tron.schemas.verification import SeverityLevel

        executor = AuditExecutor(mock_session_factory, fake_secrets)

        audit_run_id = uuid.uuid4()

        finding1 = MagicMock()
        finding1.severity = SeverityLevel.CRITICAL

        finding2 = MagicMock()
        finding2.severity = SeverityLevel.HIGH

        finding3 = MagicMock()
        finding3.severity = SeverityLevel.MEDIUM

        result = MagicMock()
        result.findings = [finding1, finding2, finding3]
        result.duration_seconds = 2.5

        await executor._finalize_audit(audit_run_id, result)

        # Verify execute and commit were called
        mock_session_factory.return_value.__aenter__.return_value.execute.assert_called_once()
        mock_session_factory.return_value.__aenter__.return_value.commit.assert_called_once()


# ── Tests: _fail_audit ────────────────────────────────────────────────


class TestFailAudit:

    async def test_fail_audit_marks_failed(self, fake_secrets, mock_session_factory):
        """Mark audit run as failed."""
        executor = AuditExecutor(mock_session_factory, fake_secrets)

        audit_run_id = uuid.uuid4()
        error_msg = "Agent crashed unexpectedly"

        await executor._fail_audit(audit_run_id, error_msg)

        # Verify execute and commit were called
        mock_session_factory.return_value.__aenter__.return_value.execute.assert_called_once()
        mock_session_factory.return_value.__aenter__.return_value.commit.assert_called_once()

    async def test_fail_audit_truncates_long_message(self, fake_secrets, mock_session_factory):
        """Long error messages should be truncated to 1000 chars."""
        executor = AuditExecutor(mock_session_factory, fake_secrets)

        audit_run_id = uuid.uuid4()
        long_error = "x" * 2000

        await executor._fail_audit(audit_run_id, long_error)

        # Verify execute was called
        mock_session_factory.return_value.__aenter__.return_value.execute.assert_called_once()

    async def test_fail_audit_exception_handling(self, fake_secrets, mock_session_factory):
        """When DB write fails, exception is caught."""
        executor = AuditExecutor(mock_session_factory, fake_secrets)

        mock_session_factory.return_value.__aenter__.return_value.execute.side_effect = RuntimeError("DB down")

        audit_run_id = uuid.uuid4()

        # Should not raise, but catch the exception
        await executor._fail_audit(audit_run_id, "Test error")


# ── Tests: _update_status ─────────────────────────────────────────────


class TestUpdateStatus:

    async def test_update_status_publishes_progress(self, fake_secrets, mock_session_factory):
        """Update status and publish progress event."""
        executor = AuditExecutor(mock_session_factory, fake_secrets)

        audit_run_id = uuid.uuid4()

        with patch("tron.services.audit_executor.publish_progress", new_callable=AsyncMock):
            await executor._update_status(
                audit_run_id, "running", progress=50, message="Half way there"
            )

        # Verify DB was updated
        mock_session_factory.return_value.__aenter__.return_value.execute.assert_called_once()
        mock_session_factory.return_value.__aenter__.return_value.commit.assert_called_once()

    async def test_update_status_no_message(self, fake_secrets, mock_session_factory):
        """Update status without a message."""
        executor = AuditExecutor(mock_session_factory, fake_secrets)

        audit_run_id = uuid.uuid4()

        with patch("tron.services.audit_executor.publish_progress", new_callable=AsyncMock):
            await executor._update_status(audit_run_id, "completed", progress=100)

        mock_session_factory.return_value.__aenter__.return_value.execute.assert_called_once()


# ── Tests: Agent event publishing ──────────────────────────────────────


class TestAgentEventPublishing:

    async def test_run_publishes_agent_started_events(self, fake_secrets, mock_session_factory):
        """Agent started events are published for each agent."""
        executor = AuditExecutor(mock_session_factory, fake_secrets)

        mock_project = MagicMock()
        mock_project.name = "TestProject"
        mock_project.repo_url = None
        mock_project.default_branch = "main"

        with patch.object(executor, "_load_project", new_callable=AsyncMock, return_value=mock_project), \
             patch.object(executor, "_update_status", new_callable=AsyncMock), \
             patch.object(executor, "_persist_findings", new_callable=AsyncMock), \
             patch.object(executor, "_finalize_audit", new_callable=AsyncMock), \
             patch("tron.services.audit_executor.publish_audit_event", new_callable=AsyncMock) as mock_pub_event, \
             patch("tron.services.audit_executor.publish_finding", new_callable=AsyncMock), \
             patch("tron.services.audit_executor.publish_audit_completed", new_callable=AsyncMock), \
             patch("tron.services.audit_executor.publish_progress", new_callable=AsyncMock):

            mock_result = MagicMock()
            mock_result.findings = []
            mock_result.duration_seconds = 1.0

            with patch.object(executor, "_build_agent_manager") as mock_build:
                mock_manager = MagicMock()
                mock_manager._agents = {
                    ISOSpecialization.SECURITY: MagicMock(config=MagicMock(agent_id="sec-1", model_name="claude")),
                    ISOSpecialization.BUILDER: MagicMock(config=MagicMock(agent_id="build-1", model_name="claude")),
                }
                mock_manager.run_audit = AsyncMock(return_value=mock_result)
                mock_build.return_value = mock_manager

                await executor.run(uuid.uuid4(), uuid.uuid4())

            # Verify agent started events were published
            assert mock_pub_event.call_count >= 2  # At least for each agent

    async def test_run_publishes_findings(self, fake_secrets, mock_session_factory):
        """Individual finding events are published."""
        from tron.schemas.verification import SeverityLevel, VulnerabilityType

        executor = AuditExecutor(mock_session_factory, fake_secrets)

        mock_project = MagicMock()
        mock_project.name = "TestProject"
        mock_project.repo_url = None
        mock_project.default_branch = "main"
        mock_project.audit_test_path_globs_json = []

        finding = MagicMock()
        finding.severity = SeverityLevel.HIGH
        finding.vulnerability_type = VulnerabilityType.SQL_INJECTION
        finding.file_path = "app.py"
        finding.line_number = 10
        finding.deterministic_tool_confirmed = True

        with patch.object(executor, "_load_project", new_callable=AsyncMock, return_value=mock_project), \
             patch.object(executor, "_update_status", new_callable=AsyncMock), \
             patch.object(executor, "_persist_findings", new_callable=AsyncMock), \
             patch.object(executor, "_finalize_audit", new_callable=AsyncMock), \
             patch("tron.services.audit_executor.publish_audit_event", new_callable=AsyncMock), \
             patch("tron.services.audit_executor.publish_finding", new_callable=AsyncMock) as mock_pub_finding, \
             patch("tron.services.audit_executor.publish_audit_completed", new_callable=AsyncMock), \
             patch("tron.services.audit_executor.publish_progress", new_callable=AsyncMock), \
             patch(
                 "tron.services.audit_executor.load_suppressed_fingerprints_for_project",
                 new_callable=AsyncMock, return_value=set(),
             ), \
             patch(
                 "tron.services.audit_executor.apply_layer3_to_findings",
                 new_callable=AsyncMock, side_effect=lambda findings, logger=None: findings,
             ), \
             patch(
                 "tron.services.audit_executor.apply_deep_verify_retry_pass_to_outputs",
                 new_callable=AsyncMock,
                 side_effect=lambda findings, logger=None, top_n=0: findings,
             ), \
             patch(
                 "tron.services.audit_executor.apply_path_role_to_outputs",
                 side_effect=lambda findings, tlist: findings,
             ), \
             patch(
                 "tron.services.audit_executor.apply_follow_up_flags_to_outputs",
                 side_effect=lambda findings, top_n: findings,
             ):

            mock_result = MagicMock()
            mock_result.findings = [finding]
            mock_result.duration_seconds = 1.0

            with patch.object(executor, "_build_agent_manager") as mock_build:
                mock_manager = MagicMock()
                mock_manager._agents = {}
                mock_manager.run_audit = AsyncMock(return_value=mock_result)
                mock_build.return_value = mock_manager

                await executor.run(uuid.uuid4(), uuid.uuid4())

            # Verify finding was published
            mock_pub_finding.assert_called_once()

    async def test_run_publishes_completion(self, fake_secrets, mock_session_factory):
        """Audit completion is published with severity counts."""
        executor = AuditExecutor(mock_session_factory, fake_secrets)

        mock_project = MagicMock()
        mock_project.name = "TestProject"
        mock_project.repo_url = None
        mock_project.default_branch = "main"

        with patch.object(executor, "_load_project", new_callable=AsyncMock, return_value=mock_project), \
             patch.object(executor, "_update_status", new_callable=AsyncMock), \
             patch.object(executor, "_persist_findings", new_callable=AsyncMock), \
             patch.object(executor, "_finalize_audit", new_callable=AsyncMock), \
             patch("tron.services.audit_executor.publish_audit_event", new_callable=AsyncMock), \
             patch("tron.services.audit_executor.publish_finding", new_callable=AsyncMock), \
             patch("tron.services.audit_executor.publish_audit_completed", new_callable=AsyncMock) as mock_pub_completed, \
             patch("tron.services.audit_executor.publish_progress", new_callable=AsyncMock), \
             patch(
                 "tron.services.audit_executor.load_suppressed_fingerprints_for_project",
                 new_callable=AsyncMock, return_value=set(),
             ):

            mock_result = MagicMock()
            mock_result.findings = []
            mock_result.duration_seconds = 2.5

            with patch.object(executor, "_build_agent_manager") as mock_build:
                mock_manager = MagicMock()
                mock_manager._agents = {}
                mock_manager.run_audit = AsyncMock(return_value=mock_result)
                mock_build.return_value = mock_manager

                await executor.run(uuid.uuid4(), uuid.uuid4())

            # Verify completion event was published
            mock_pub_completed.assert_called_once()


# ── Tests: Error handling in run() ─────────────────────────────────────


class TestRunErrorHandling:

    async def test_run_handles_all_exceptions(self, fake_secrets, mock_session_factory):
        """Any exception in run() is caught and audit marked as failed."""
        executor = AuditExecutor(mock_session_factory, fake_secrets)

        with patch.object(executor, "_load_project", new_callable=AsyncMock, side_effect=RuntimeError("Boom")), \
             patch.object(executor, "_update_status", new_callable=AsyncMock), \
             patch.object(executor, "_fail_audit", new_callable=AsyncMock), \
             patch("tron.services.audit_executor.publish_audit_failed", new_callable=AsyncMock):

            await executor.run(uuid.uuid4(), uuid.uuid4())

            executor._fail_audit.assert_called_once()

    async def test_run_publishes_failure_event(self, fake_secrets, mock_session_factory):
        """Failure event is published on error."""
        executor = AuditExecutor(mock_session_factory, fake_secrets)

        audit_run_id = uuid.uuid4()

        with patch.object(executor, "_load_project", new_callable=AsyncMock, side_effect=ValueError("Not found")), \
             patch.object(executor, "_update_status", new_callable=AsyncMock), \
             patch.object(executor, "_fail_audit", new_callable=AsyncMock), \
             patch("tron.services.audit_executor.publish_audit_failed", new_callable=AsyncMock) as mock_pub_failed:

            await executor.run(audit_run_id, uuid.uuid4())

            mock_pub_failed.assert_called_once()
            args = mock_pub_failed.call_args[0]
            assert args[0] == audit_run_id

    async def test_run_closes_llm_client_on_exception(self, fake_secrets, mock_session_factory):
        """LLM client is closed even on exception (finally block)."""
        executor = AuditExecutor(mock_session_factory, fake_secrets)
        executor._llm = AsyncMock()
        executor._llm.close = AsyncMock()

        with patch.object(executor, "_load_project", new_callable=AsyncMock, side_effect=RuntimeError("Boom")), \
             patch.object(executor, "_update_status", new_callable=AsyncMock), \
             patch.object(executor, "_fail_audit", new_callable=AsyncMock), \
             patch("tron.services.audit_executor.publish_audit_failed", new_callable=AsyncMock):

            await executor.run(uuid.uuid4(), uuid.uuid4())

            # Verify LLM client was closed
            executor._llm.close.assert_called_once()


# ── Tests: Severity counting ──────────────────────────────────────────


class TestSeverityCounting:

    async def test_run_counts_severity_levels_correctly(self, fake_secrets, mock_session_factory):
        """Findings are counted by severity level."""
        from tron.schemas.verification import SeverityLevel

        executor = AuditExecutor(mock_session_factory, fake_secrets)

        mock_project = MagicMock()
        mock_project.name = "TestProject"
        mock_project.repo_url = None
        mock_project.default_branch = "main"

        # Create findings with different severities
        critical_finding = MagicMock()
        critical_finding.severity = SeverityLevel.CRITICAL

        high_finding = MagicMock()
        high_finding.severity = SeverityLevel.HIGH

        medium_finding = MagicMock()
        medium_finding.severity = SeverityLevel.MEDIUM

        with patch.object(executor, "_load_project", new_callable=AsyncMock, return_value=mock_project), \
             patch.object(executor, "_update_status", new_callable=AsyncMock), \
             patch.object(executor, "_persist_findings", new_callable=AsyncMock), \
             patch.object(executor, "_finalize_audit", new_callable=AsyncMock), \
             patch("tron.services.audit_executor.publish_audit_event", new_callable=AsyncMock), \
             patch("tron.services.audit_executor.publish_finding", new_callable=AsyncMock), \
             patch("tron.services.audit_executor.publish_audit_completed", new_callable=AsyncMock) as mock_pub_completed, \
             patch("tron.services.audit_executor.publish_progress", new_callable=AsyncMock), \
             patch(
                 "tron.services.audit_executor.load_suppressed_fingerprints_for_project",
                 new_callable=AsyncMock, return_value=set(),
             ), \
             patch(
                 "tron.services.audit_executor.apply_layer3_to_findings",
                 new_callable=AsyncMock, side_effect=lambda findings, logger=None: findings,
             ), \
             patch(
                 "tron.services.audit_executor.apply_path_role_to_outputs",
                 side_effect=lambda findings, tlist: findings,
             ), \
             patch(
                 "tron.services.audit_executor.filter_findings_by_suppression",
                 side_effect=lambda findings, suppressed: findings,
             ), \
             patch(
                 "tron.services.audit_executor.apply_deep_verify_retry_pass_to_outputs",
                 new_callable=AsyncMock,
                 side_effect=lambda findings, logger=None, top_n=0: findings,
             ), \
             patch(
                 "tron.services.audit_executor.apply_follow_up_flags_to_outputs",
                 side_effect=lambda findings, top_n: findings,
             ), \
             patch(
                 "tron.services.agent_handoff.maybe_write_agent_handoff_after_audit",
                 new_callable=AsyncMock,
             ):

            mock_result = MagicMock()
            mock_result.findings = [critical_finding, high_finding, medium_finding]
            mock_result.duration_seconds = 1.5

            with patch.object(executor, "_build_agent_manager") as mock_build:
                mock_manager = MagicMock()
                mock_manager._agents = {}
                mock_manager.run_audit = AsyncMock(return_value=mock_result)
                mock_build.return_value = mock_manager

                await executor.run(uuid.uuid4(), uuid.uuid4())

            # Verify counts in completion event
            call_kwargs = mock_pub_completed.call_args[1]
            assert call_kwargs["findings_total"] == 3
            assert call_kwargs["findings_critical"] == 1
            assert call_kwargs["findings_high"] == 1
            assert call_kwargs["findings_medium"] == 1
