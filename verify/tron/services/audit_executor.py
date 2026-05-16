"""
Audit Execution Service.

Bridges the API layer to the agent framework. Takes a queued audit run,
pulls project source files, initializes agents with keyvault secrets,
runs the analysis pipeline, and persists findings to the database.

This is the real execution path — replaces the stub in audits.py.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tron.agents.base import ISOConfig, ISOSpecialization, LLMProvider
from tron.agents.builder_iso import BuilderISO
from tron.agents.compliance_iso import ComplianceISO
from tron.agents.documentation_iso import DocumentationISO
from tron.agents.manager import AuditManager, AuditRequest, AuditResult
from tron.agents.performance_iso import PerformanceISO
from tron.agents.qa_iso import QAISO
from tron.agents.security_iso import SecurityISO
from tron.domain.models import AuditRun, Finding, Project
from tron.infra.llm.client import DEFAULT_ANTHROPIC_FAST_MODEL, LLMClient
from tron.infra.llm.usage_context import LLMUsageRecordContext, llm_usage_scope
from tron.infra.redis.pubsub import (
    AuditEvent,
    publish_audit_completed,
    publish_audit_event,
    publish_audit_failed,
    publish_finding,
    publish_progress,
)
from tron.schemas.verification import FindingOutput, SeverityLevel
from tron.services.graph_sync import sync_project_graph
from tron.services.layer3_findings import apply_layer3_to_findings
from tron.services.repo_scanner import RepoScanner, RepoScanError, detect_languages

logger = logging.getLogger(__name__)


# ── Severity ordering for DB storage ──

_SEVERITY_ORDER = {
    SeverityLevel.CRITICAL: "critical",
    SeverityLevel.HIGH: "high",
    SeverityLevel.MEDIUM: "medium",
    SeverityLevel.LOW: "low",
    SeverityLevel.INFO: "info",
}


class AuditExecutor:
    """Runs the full audit pipeline for a given audit run.

    Usage:
        executor = AuditExecutor(session_factory, secrets)
        await executor.run(audit_run_id, project_id)
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        secrets: Dict[str, str],
    ) -> None:
        self._sf = session_factory
        self._secrets = secrets
        self._llm = LLMClient(
            anthropic_key=secrets.get("llm/anthropic-key"),
            openai_key=secrets.get("llm/openai-key"),
        )

    async def run(self, audit_run_id: UUID, project_id: UUID) -> None:
        """Execute a full audit run."""
        logger.info("AuditExecutor starting: run=%s project=%s", audit_run_id, project_id)

        try:
            await self._update_status(
                audit_run_id, "running", progress=5,
                message="Initializing audit pipeline",
            )

            # 1. Load project metadata
            project = await self._load_project(project_id)
            if not project:
                raise ValueError(f"Project {project_id} not found")

            await self._update_status(
                audit_run_id, "running", progress=10,
                message=f"Project loaded: {project.name}",
            )

            # 2. Collect source files to analyze
            file_contents = await self._collect_source_files(project)

            await self._update_status(
                audit_run_id, "running", progress=20,
                message=f"Collected {len(file_contents)} files for analysis",
            )

            await self._update_status(
                audit_run_id, "running", progress=22,
                message="Syncing dependency graph (code_files / file_dependencies)",
            )
            async with self._sf() as gsession:
                await sync_project_graph(gsession, project_id, file_contents)
                await gsession.commit()

            # 3. Initialize agents (compliance packs from project + TRON_COMPLIANCE_PACKS)
            cref = self._compliance_reference_context(project)
            manager = self._build_agent_manager(compliance_reference_context=cref)

            # Publish agent start events
            for spec, agent in manager._agents.items():
                await publish_audit_event(
                    audit_run_id,
                    AuditEvent.AGENT_STARTED,
                    {
                        "agent_id": agent.config.agent_id,
                        "specialization": spec.value,
                        "model": agent.config.model_name,
                    },
                )

            await self._update_status(
                audit_run_id, "running", progress=30,
                message="Agents initialized — starting analysis",
            )

            # 4. Run the audit
            request = AuditRequest(
                project_id=project_id,
                audit_run_id=audit_run_id,
                file_contents=file_contents,
                languages=self._detect_languages(file_contents),
            )

            with llm_usage_scope(
                LLMUsageRecordContext(
                    project_id=project_id,
                    workflow_id=None,
                    workflow_run_id=str(audit_run_id),
                    operation_mode="audit",
                    operation_detail="audit_executor",
                )
            ):
                result = await manager.run_audit(request)

            await self._update_status(
                audit_run_id, "running", progress=70,
                message="Layer 3: execution verification (sandbox) for critical/high findings",
            )
            result.findings = await apply_layer3_to_findings(
                result.findings, logger=logger
            )

            await self._update_status(
                audit_run_id, "running", progress=75,
                message=f"Analysis complete — {len(result.findings)} findings after verification",
            )

            # Publish individual finding events
            for fo in result.findings:
                await publish_finding(
                    audit_run_id,
                    severity=fo.severity.value,
                    title=f"{fo.vulnerability_type.value}: {fo.file_path}:{fo.line_number}",
                    file_path=fo.file_path,
                    line_number=fo.line_number,
                    tool_confirmed=fo.deterministic_tool_confirmed,
                )

            await self._update_status(
                audit_run_id, "running", progress=85,
                message="Persisting findings to database",
            )

            # 5. Persist findings to database
            await self._persist_findings(audit_run_id, project_id, result)

            await self._update_status(
                audit_run_id, "running", progress=95,
                message="Finalizing audit results",
            )

            # 6. Update audit run with final counts
            await self._finalize_audit(audit_run_id, result)

            # Publish completion event via Redis
            sev_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
            for f in result.findings:
                key = f.severity.value
                if key in sev_counts:
                    sev_counts[key] += 1

            await publish_audit_completed(
                audit_run_id,
                findings_total=len(result.findings),
                findings_critical=sev_counts["critical"],
                findings_high=sev_counts["high"],
                findings_medium=sev_counts["medium"],
                findings_low=sev_counts["low"],
                duration_seconds=result.duration_seconds,
            )

            from tron.services.agent_handoff import maybe_write_agent_handoff_after_audit

            handoff_payload = [
                {
                    "severity": f.severity.value,
                    "file_path": f.file_path,
                    "line_number": f.line_number,
                    "vulnerability_type": f.vulnerability_type.value,
                }
                for f in result.findings
            ]
            await maybe_write_agent_handoff_after_audit(
                audit_run_id=audit_run_id,
                project_id=project_id,
                preloaded_findings=handoff_payload,
            )

            logger.info(
                "AuditExecutor completed: run=%s findings=%d duration=%.1fs",
                audit_run_id,
                len(result.findings),
                result.duration_seconds,
            )

        except Exception as exc:
            logger.exception("AuditExecutor failed: run=%s", audit_run_id)
            await self._fail_audit(audit_run_id, str(exc))
            await publish_audit_failed(audit_run_id, str(exc))

        finally:
            await self._llm.close()

    # ── Internals ──────────────────────────────────────────────────

    def _compliance_reference_context(self, project: Project) -> str:
        import os

        from tron.standards.control_packs import format_packs_for_prompt

        env_ids = [
            x.strip()
            for x in (os.environ.get("TRON_COMPLIANCE_PACKS") or "").split(",")
            if x.strip()
        ]
        ids: list[str] = []
        raw = getattr(project, "compliance_control_pack_ids", None)
        if isinstance(raw, list):
            ids.extend(str(x) for x in raw)
        for e in env_ids:
            if e not in ids:
                ids.append(e)
        return format_packs_for_prompt(ids)

    def _build_agent_manager(self, compliance_reference_context: str = "") -> AuditManager:
        """Create and configure the AuditManager with SecurityISO."""
        manager = AuditManager(
            secrets=self._secrets,
            llm_client=self._llm,
        )

        # Register SecurityISO (primary agent for Phase 1)
        #
        # Determine provider based on available keys.
        # Prefer Anthropic; fall back to OpenAI if Anthropic key missing.
        anthropic_key = self._secrets.get("llm/anthropic-key", "")
        openai_key = self._secrets.get("llm/openai-key", "")

        if anthropic_key and anthropic_key != "REPLACE_ME_IN_VAULT":
            provider = LLMProvider.ANTHROPIC
            model = DEFAULT_ANTHROPIC_FAST_MODEL
        elif openai_key and openai_key != "REPLACE_ME_IN_VAULT":
            provider = LLMProvider.OPENAI
            model = "gpt-4o"
        else:
            logger.warning(
                "No LLM keys configured in keyvault. "
                "Audit will run deterministic tools only (no LLM analysis)."
            )
            # Still register the agent — it will skip LLM and return
            # only tool-based findings (if tools are available).
            provider = LLMProvider.ANTHROPIC
            model = DEFAULT_ANTHROPIC_FAST_MODEL

        security_config = ISOConfig(
            specialization=ISOSpecialization.SECURITY,
            agent_id="security-iso-primary",
            model_provider=provider,
            model_name=model,
            temperature=0.1,
            max_tokens=4000,
            max_duration_seconds=300,
            tools_required=("bandit", "semgrep"),
            prompt_template_id="security-v1",
        )

        security_agent = SecurityISO(
            config=security_config,
            secrets=self._secrets,
            llm_client=self._llm,
        )

        manager.register_agent(security_agent)

        # BuilderISO — Dockerfiles, CI/CD, dependency manifests
        builder_config = ISOConfig(
            specialization=ISOSpecialization.BUILDER,
            agent_id="builder-iso-primary",
            model_provider=provider,
            model_name=model,
            temperature=0.1,
            max_tokens=4000,
            max_duration_seconds=300,
            tools_required=(),  # pip-audit/npm-audit run if manifests exist
            prompt_template_id="builder-v1",
        )
        builder_agent = BuilderISO(
            config=builder_config,
            secrets=self._secrets,
            llm_client=self._llm,
        )
        manager.register_agent(builder_agent)

        # PerformanceISO — N+1 queries, blocking I/O, resource leaks
        perf_config = ISOConfig(
            specialization=ISOSpecialization.PERFORMANCE,
            agent_id="performance-iso-primary",
            model_provider=provider,
            model_name=model,
            temperature=0.1,
            max_tokens=4000,
            max_duration_seconds=300,
            tools_required=(),  # Pure LLM analysis
            prompt_template_id="performance-v1",
        )
        perf_agent = PerformanceISO(
            config=perf_config,
            secrets=self._secrets,
            llm_client=self._llm,
        )
        manager.register_agent(perf_agent)

        qa_config = ISOConfig(
            specialization=ISOSpecialization.QA,
            agent_id="qa-iso-primary",
            model_provider=provider,
            model_name=model,
            temperature=0.1,
            max_tokens=4000,
            max_duration_seconds=300,
            tools_required=(),
            prompt_template_id="qa-v1",
        )
        manager.register_agent(
            QAISO(config=qa_config, secrets=self._secrets, llm_client=self._llm)
        )

        comp_config = ISOConfig(
            specialization=ISOSpecialization.COMPLIANCE,
            agent_id="compliance-iso-primary",
            model_provider=provider,
            model_name=model,
            temperature=0.1,
            max_tokens=4000,
            max_duration_seconds=300,
            tools_required=(),
            prompt_template_id="compliance-v1",
            compliance_reference_context=compliance_reference_context,
        )
        manager.register_agent(
            ComplianceISO(config=comp_config, secrets=self._secrets, llm_client=self._llm)
        )

        doc_config = ISOConfig(
            specialization=ISOSpecialization.DOCUMENTATION,
            agent_id="documentation-iso-primary",
            model_provider=provider,
            model_name=model,
            temperature=0.1,
            max_tokens=4000,
            max_duration_seconds=300,
            tools_required=(),
            prompt_template_id="documentation-v1",
        )
        manager.register_agent(
            DocumentationISO(config=doc_config, secrets=self._secrets, llm_client=self._llm)
        )

        return manager

    async def _load_project(self, project_id: UUID) -> Optional[Project]:
        """Load project from database."""
        async with self._sf() as session:
            result = await session.execute(
                select(Project).where(
                    Project.id == project_id,
                    Project.deleted_at.is_(None),
                )
            )
            return result.scalar_one_or_none()

    async def _collect_source_files(
        self, project: Project
    ) -> Dict[str, str]:
        """Collect source files for analysis.

        If the project has a repo_url, clone it and scan real files.
        Only uses demo code when repo_url is explicitly None/empty
        (intentional pipeline testing mode).

        Raises RepoScanError if a configured repo fails to clone —
        never silently falls back to demo code for real projects.
        """
        if project.repo_url:
            logger.info(
                "Scanning real repo: %s@%s",
                project.repo_url,
                project.default_branch or "main",
            )
            scanner = RepoScanner(
                max_files=2000,        # Support larger projects
                max_total_size=50 * 1024 * 1024,  # 50 MB
            )
            # Let RepoScanError propagate — callers catch Exception
            # and mark the audit as failed with a clear error message.
            files = await scanner.scan(
                repo_url=project.repo_url,
                branch=project.default_branch or "main",
            )
            if not files:
                raise RepoScanError(
                    f"Repo cloned but 0 analyzable files found in "
                    f"{project.repo_url}@{project.default_branch or 'main'}"
                )
            return files

        # Demo mode: only when repo_url is explicitly not set
        logger.info("Using demo source files (no repo_url configured)")
        return self._demo_source_files()

    @staticmethod
    def _demo_source_files() -> Dict[str, str]:
        """Return a demo vulnerable Flask app for testing."""
        demo_code = '''\
import os
import subprocess
import sqlite3
import pickle
import hashlib
from flask import Flask, request, render_template_string

app = Flask(__name__)

# Hardcoded secret (B105)
DATABASE_PASSWORD = "super_secret_password_123"
API_KEY = "sk-1234567890abcdef"

@app.route("/search")
def search():
    # SQL Injection (B608)
    query = request.args.get("q", "")
    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE name = '" + query + "'")
    results = cursor.fetchall()
    return str(results)

@app.route("/run")
def run_command():
    # Command Injection (B602)
    cmd = request.args.get("cmd", "ls")
    output = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE)
    return output.stdout.read()

@app.route("/template")
def template():
    # XSS via template injection
    name = request.args.get("name", "World")
    template = "<h1>Hello " + name + "!</h1>"
    return render_template_string(template)

@app.route("/load")
def load_data():
    # Insecure deserialization (B301)
    data = request.get_data()
    obj = pickle.loads(data)
    return str(obj)

@app.route("/hash")
def weak_hash():
    # Weak hash (B303)
    password = request.args.get("pw", "")
    hashed = hashlib.md5(password.encode()).hexdigest()
    return hashed

@app.route("/redirect")
def open_redirect():
    # Open redirect
    url = request.args.get("url", "/")
    return app.redirect(url)

if __name__ == "__main__":
    # Debug mode enabled (B201)
    app.run(debug=True, host="0.0.0.0")
'''
        return {"app.py": demo_code}

    @staticmethod
    def _detect_languages(file_contents: Dict[str, str]) -> List[str]:
        """Detect programming languages from file extensions."""
        return detect_languages(file_contents)

    async def _persist_findings(
        self,
        audit_run_id: UUID,
        project_id: UUID,
        result: AuditResult,
    ) -> None:
        """Write FindingOutput objects to the findings table."""
        if not result.findings:
            logger.info("No findings to persist for audit %s", audit_run_id)
            return

        async with self._sf() as session:
            for fo in result.findings:
                finding = Finding(
                    audit_run_id=audit_run_id,
                    project_id=project_id,
                    fingerprint=fo.finding_fingerprint,
                    rule_id=fo.vulnerability_type.value,
                    file_path=fo.file_path,
                    line_start=fo.line_number,
                    line_end=fo.line_end,
                    severity=fo.severity.value,
                    category=fo.vulnerability_type.value,
                    title=f"{fo.vulnerability_type.value}: {fo.file_path}:{fo.line_number}",
                    description=fo.description,
                    suggested_fix=fo.fix_suggestion,
                    status="open",
                    code_snippet=fo.code_snippet,
                )
                session.add(finding)

            await session.commit()

        logger.info(
            "Persisted %d findings for audit %s",
            len(result.findings),
            audit_run_id,
        )

    async def _finalize_audit(
        self, audit_run_id: UUID, result: AuditResult
    ) -> None:
        """Update audit run with final counts and status."""
        sev_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for f in result.findings:
            key = f.severity.value
            if key in sev_counts:
                sev_counts[key] += 1

        async with self._sf() as session:
            await session.execute(
                update(AuditRun)
                .where(AuditRun.id == audit_run_id)
                .values(
                    status="completed",
                    progress=100,
                    findings_total=len(result.findings),
                    findings_critical=sev_counts["critical"],
                    findings_high=sev_counts["high"],
                    findings_medium=sev_counts["medium"],
                    findings_low=sev_counts["low"],
                    completed_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()

    async def _fail_audit(self, audit_run_id: UUID, error: str) -> None:
        """Mark audit as failed."""
        try:
            async with self._sf() as session:
                await session.execute(
                    update(AuditRun)
                    .where(AuditRun.id == audit_run_id)
                    .values(
                        status="failed",
                        error_message=error[:1000],
                        completed_at=datetime.now(timezone.utc),
                    )
                )
                await session.commit()
        except Exception:
            logger.exception("Failed to mark audit %s as failed", audit_run_id)

    async def _update_status(
        self, audit_run_id: UUID, status: str, progress: int = 0,
        message: str = "",
    ) -> None:
        """Update audit run status and progress, and publish to Redis."""
        async with self._sf() as session:
            await session.execute(
                update(AuditRun)
                .where(AuditRun.id == audit_run_id)
                .values(status=status, progress=progress)
            )
            await session.commit()

        # Publish real-time event (best-effort, never fails the pipeline)
        await publish_progress(audit_run_id, status, progress, message)
