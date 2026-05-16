"""
Temporal Activity Definitions for Tron Audit & Fix Workflows.

Activities are the individual steps that workflows execute. Each activity
is a standalone async function decorated with @activity.defn. They handle:
  - Database access (sessions)
  - External service calls (LLM, git clone, sandbox)
  - Redis pub/sub progress events

Activities run in the Temporal worker process with access to database,
Redis, and keyvault secrets loaded at worker startup.

Architecture ref: docs/architecture/AI_AGENT_ARCHITECTURE.md §5
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from temporalio import activity

from tron.infra.llm.client import DEFAULT_ANTHROPIC_FAST_MODEL

logger = logging.getLogger(__name__)


# ── Activity Input/Output Dataclasses ─────────────────────────────────
# Temporal requires serializable inputs/outputs. Using dataclasses
# with simple types (no ORM models across the wire).


@dataclass
class AuditInput:
    """Input to start an audit workflow."""
    audit_run_id: str  # UUID as string (serialization)
    project_id: str
    triggered_by: Optional[str] = None
    scope: str = "full"  # full | security | quality | performance
    # BUILD mode: passed only for BuildWorkflow — steers BuilderISO blueprint
    build_task: Optional[str] = None


@dataclass
class PlanJobInput:
    """PLAN mode — generate plan artifact for a project."""

    project_id: str
    goals: str = ""
    constraints: str = ""
    # When True and project has repo_url, shallow-clone and write `.tron/*` (proposal layout).
    write_tron_files: bool = True
    # Interactive wizard answers from the admin UI (optional).
    questionnaire: Optional[Dict[str, Any]] = None


@dataclass
class PlanSummary:
    project_id: str
    ok: bool
    message: str = ""
    tron_files_written: List[str] = field(default_factory=list)


@dataclass
class BuildJobInput:
    """BUILD mode — run builder ISO against repo with a task description."""

    project_id: str
    task: str
    build_run_id: str


@dataclass
class EvolveJobInput:
    """EVOLVE mode — iterative improvement pass (Builder ISO + persisted artifact)."""

    project_id: str
    directive: str
    evolve_run_id: str


@dataclass
class BuildSummary:
    project_id: str
    findings_count: int
    ok: bool
    message: str = ""
    artifact_json: str = ""


@dataclass
class EvolveSummary:
    project_id: str
    findings_count: int
    ok: bool
    message: str = ""
    evolve_run_id: str = ""


@dataclass
class BuildQualityGateEval:
    passed: bool
    criteria_json: str


@dataclass
class BuildValidationOutcome:
    ok: bool
    command: str
    exit_code: int
    log_tail: str


@dataclass
class BuildGitPushOutcome:
    attempted: bool
    branch: str
    detail: str


@dataclass
class ProjectMeta:
    """Project metadata extracted from DB."""
    project_id: str
    name: str
    repo_url: Optional[str]
    default_branch: str


@dataclass
class ScanResult:
    """Result from scanning a repository.

    file_contents is stored in Redis to avoid Temporal's 4MB gRPC payload limit.
    The redis_key field holds the cache key; file_contents is only populated
    when retrieved from Redis inside agent activities.
    """
    file_count: int
    total_size_kb: float
    languages: List[str]
    redis_key: str = ""
    file_contents: Optional[Dict[str, str]] = None


@dataclass
class AgentResult:
    """Result from running a single ISO agent."""
    agent_id: str
    specialization: str
    findings_count: int
    findings_json: str  # JSON-serialized list of FindingOutput dicts
    duration_seconds: float
    llm_tokens_used: int
    llm_cost_usd: float
    errors: List[str]
    threat_intel_alerts: List[str] = field(default_factory=list)


@dataclass
class AuditSummary:
    """Final audit summary after all agents complete."""
    audit_run_id: str
    findings_total: int
    findings_critical: int
    findings_high: int
    findings_medium: int
    findings_low: int
    duration_seconds: float
    agents_run: int
    errors: List[str] = field(default_factory=list)


@dataclass
class VerificationResult:
    """Result from Layer 3 execution verification."""
    verified_count: int
    rejected_count: int
    unverified_count: int
    skipped_count: int
    confidence_adjustments: List[Dict[str, Any]]


@dataclass
class FindingInput:
    """Input to the fix workflow for a single finding."""
    finding_id: str
    audit_run_id: str
    project_id: str
    file_path: str
    line_number: int
    vulnerability_type: str
    severity: str
    description: str
    code_snippet: str


@dataclass
class FixAttempt:
    """Result from a single fix attempt."""
    iteration: int
    fix_code: str
    verification_passed: bool
    verification_output: str
    error_message: Optional[str] = None


@dataclass
class FixResult:
    """Final result of the fix workflow."""
    finding_id: str
    success: bool
    iterations_completed: int
    final_fix: Optional[str] = None
    pr_url: Optional[str] = None
    error_message: Optional[str] = None


# ── Activity Implementations ──────────────────────────────────────────


@activity.defn
async def load_project_metadata(audit_input: AuditInput) -> ProjectMeta:
    """Load project metadata from the database.

    Phase 1: Context Gathering
    """
    from sqlalchemy import select, update
    from tron.domain.models import AuditRun, Project
    from tron.infra.db.session import _session_factory

    project_id = UUID(audit_input.project_id)
    audit_run_id = UUID(audit_input.audit_run_id)

    async with _session_factory() as session:
        result = await session.execute(
            select(Project).where(
                Project.id == project_id,
                Project.deleted_at.is_(None),
            )
        )
        project = result.scalar_one_or_none()

    if not project:
        raise ValueError(f"Project {project_id} not found")

    # First durable activity: move DB off ``queued`` so Live / workflow-runs match reality.
    async with _session_factory() as session:
        await session.execute(
            update(AuditRun)
            .where(AuditRun.id == audit_run_id, AuditRun.status == "queued")
            .values(status="running", progress=5)
        )
        await session.commit()

    activity.logger.info("Loaded project: %s (%s)", project.name, project.repo_url or "no repo")

    return ProjectMeta(
        project_id=str(project.id),
        name=project.name,
        repo_url=project.repo_url,
        default_branch=project.default_branch or "main",
    )


@activity.defn
async def mark_audit_run_failed(audit_run_id: str, message: str, stack: Optional[str] = None) -> None:
    """Persist ``failed`` when ``AuditWorkflow`` aborts (Temporal activity failure / crash)."""
    from sqlalchemy import update

    from tron.domain.models import AuditRun
    from tron.infra.db.session import _session_factory
    from tron.infra.redis.pubsub import publish_audit_failed

    aid = UUID(audit_run_id)
    msg = (message or "Audit workflow failed")[:1000]

    if _session_factory is None:
        activity.logger.error("mark_audit_run_failed: no DB session factory")
        return

    async with _session_factory() as session:
        await session.execute(
            update(AuditRun)
            .where(
                AuditRun.id == aid,
                AuditRun.status.in_(("queued", "running")),
            )
            .values(
                status="failed",
                error_message=msg,
                error_stack=stack,
                completed_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    await publish_audit_failed(aid, msg)
    activity.logger.warning("Audit %s marked failed: %s", audit_run_id, msg[:200])


@activity.defn
async def scan_repository(project_meta: ProjectMeta) -> ScanResult:
    """Clone and scan the repository for source files.

    Phase 1: Context Gathering

    File contents are stored in Redis (not returned through Temporal)
    to avoid the 4 MB gRPC payload limit on large repos.
    """
    import json as _json
    from tron.services.repo_scanner import RepoScanner, RepoScanError, detect_languages
    from tron.infra.redis.client import get_redis
    from tron.infra.secrets import get_secret

    if project_meta.repo_url:
        # Retrieve token from vault for private clones
        token = None
        try:
            # 1. Try primary tron key
            token = await get_secret("github_token")
        except (KeyError, RuntimeError):
            try:
                # 2. Try the shared organization key found in vault
                token = await get_secret("enginsights:github-api-token", explicit=True)
            except (KeyError, RuntimeError):
                token = None

        scanner = RepoScanner(
            max_files=2000,
            max_total_size=50 * 1024 * 1024,
        )
        file_contents = await scanner.scan(
            repo_url=project_meta.repo_url,
            branch=project_meta.default_branch,
            github_token=token,
        )
        if not file_contents:
            raise RepoScanError(
                f"Repo cloned but 0 analyzable files found in "
                f"{project_meta.repo_url}@{project_meta.default_branch}"
            )
    else:
        activity.logger.info("No repo_url — using demo source files")
        file_contents = _demo_source_files()

    languages = detect_languages(file_contents)
    total_size = sum(len(v) for v in file_contents.values())

    activity.logger.info(
        "Scanned %d files (%.1f KB), languages: %s",
        len(file_contents),
        total_size / 1024,
        languages,
    )

    from tron.infra.db.session import _session_factory
    from tron.services.graph_sync import sync_project_graph

    pid = UUID(project_meta.project_id)
    async with _session_factory() as session:
        await sync_project_graph(session, pid, file_contents)
        await session.commit()

    # Store file contents in Redis to bypass Temporal payload limit
    redis_key = f"tron:scan:{project_meta.project_id}:{uuid4().hex[:8]}"
    redis = get_redis()
    await redis.set(redis_key, _json.dumps(file_contents), ex=3600)  # 1h TTL
    activity.logger.info("Stored scan payload in Redis: %s (%d KB)", redis_key, total_size // 1024)

    return ScanResult(
        file_count=len(file_contents),
        total_size_kb=round(total_size / 1024, 1),
        languages=languages,
        redis_key=redis_key,
    )


@activity.defn
async def run_security_agent(
    audit_input: AuditInput,
    scan_result: ScanResult,
) -> AgentResult:
    """Run SecurityISO agent.

    Phase 2: Parallel ISO Analysis
    """
    return await _run_agent(
        audit_input=audit_input,
        scan_result=scan_result,
        specialization="security",
        agent_id="security-iso-primary",
    )


@activity.defn
async def run_builder_agent(
    audit_input: AuditInput,
    scan_result: ScanResult,
) -> AgentResult:
    """Run BuilderISO agent.

    Phase 2: Parallel ISO Analysis
    """
    return await _run_agent(
        audit_input=audit_input,
        scan_result=scan_result,
        specialization="builder",
        agent_id="builder-iso-primary",
    )


@activity.defn
async def run_performance_agent(
    audit_input: AuditInput,
    scan_result: ScanResult,
) -> AgentResult:
    """Run PerformanceISO agent.

    Phase 2: Parallel ISO Analysis
    """
    return await _run_agent(
        audit_input=audit_input,
        scan_result=scan_result,
        specialization="performance",
        agent_id="performance-iso-primary",
    )


@activity.defn
async def run_qa_agent(
    audit_input: AuditInput,
    scan_result: ScanResult,
) -> AgentResult:
    """Run QAISO — test quality and coverage gaps."""
    return await _run_agent(
        audit_input=audit_input,
        scan_result=scan_result,
        specialization="qa",
        agent_id="qa-iso-primary",
    )


@activity.defn
async def run_compliance_agent(
    audit_input: AuditInput,
    scan_result: ScanResult,
) -> AgentResult:
    """Run ComplianceISO — policy / compliance heuristics."""
    return await _run_agent(
        audit_input=audit_input,
        scan_result=scan_result,
        specialization="compliance",
        agent_id="compliance-iso-primary",
    )


@activity.defn
async def run_documentation_agent(
    audit_input: AuditInput,
    scan_result: ScanResult,
) -> AgentResult:
    """Run DocumentationISO — documentation gaps."""
    return await _run_agent(
        audit_input=audit_input,
        scan_result=scan_result,
        specialization="documentation",
        agent_id="documentation-iso-primary",
    )


@activity.defn
async def verify_findings_with_sandbox(
    audit_input: AuditInput,
    agent_results: List[AgentResult],
) -> VerificationResult:
    """Layer 3: Execute verification tests in sandbox.
    
    Verifies critical/high findings by attempting exploits in Docker sandbox.
    Adjusts confidence scores based on verification results:
    - Verified: confidence +0.15
    - Rejected (false positive): removed from results
    - Unverified: confidence unchanged
    """
    import json
    from tron.verification.execution_verifier import (
        ExecutionVerifier,
        FindingSnapshot,
        VerificationStatus,
    )
    from tron.services.sandbox_client import SandboxClient
    from tron.infra.redis.pubsub import publish_progress
    
    audit_run_id = UUID(audit_input.audit_run_id)
    
    await publish_progress(
        audit_run_id,
        "running",
        70,
        "Layer 3: Verifying findings in sandbox"
    )
    
    # Initialize sandbox client
    sandbox_client = SandboxClient(logger=activity.logger)
    
    # Check if Docker is available
    if not sandbox_client.is_available():
        activity.logger.warning(
            "Layer 3: Docker not available - skipping sandbox verification"
        )
        return VerificationResult(
            verified_count=0,
            rejected_count=0,
            unverified_count=0,
            skipped_count=sum(ar.findings_count for ar in agent_results),
            confidence_adjustments=[]
        )
    
    verifier = ExecutionVerifier(
        sandbox_client=sandbox_client,
        logger=activity.logger
    )
    
    verified = 0
    rejected = 0
    unverified = 0
    skipped = 0
    adjustments = []
    
    # Parse all findings and verify critical/high severity
    for ar in agent_results:
        try:
            findings = json.loads(ar.findings_json)
        except json.JSONDecodeError:
            activity.logger.warning(f"Failed to parse findings from {ar.agent_id}")
            continue
        
        for finding_dict in findings:
            severity = finding_dict.get("severity", "").lower()
            category = finding_dict.get("category") or finding_dict.get(
                "vulnerability_type", ""
            )
            
            # Only verify critical/high findings
            if severity in ["critical", "high"]:
                finding = FindingSnapshot(
                    category=category,
                    severity=severity,
                    title=finding_dict.get("title", ""),
                    description=finding_dict.get("description", ""),
                    file_path=finding_dict.get("file_path", ""),
                    line_number=finding_dict.get("line_number", 0),
                    code_snippet=finding_dict.get("code_snippet", ""),
                    confidence=finding_dict.get("confidence", 0.5),
                )
                
                # Verify the finding
                result = await verifier.verify_finding(finding)
                
                if result.status == VerificationStatus.VERIFIED:
                    # Boost confidence
                    finding_dict["confidence"] = min(
                        1.0,
                        finding_dict.get("confidence", 0.5) + result.confidence_adjustment
                    )
                    finding_dict["sandbox_verified"] = True
                    finding_dict["verification_method"] = result.method
                    verified += 1
                    adjustments.append({
                        "finding_id": finding_dict.get("finding_fingerprint"),
                        "adjustment": result.confidence_adjustment,
                        "status": "verified",
                        "method": result.method
                    })
                    activity.logger.info(
                        f"Layer 3: VERIFIED {category} in {finding_dict.get('file_path')}"
                    )
                
                elif result.status == VerificationStatus.REJECTED:
                    # Mark for removal (false positive)
                    finding_dict["_reject"] = True
                    finding_dict["rejection_reason"] = result.reason
                    rejected += 1
                    adjustments.append({
                        "finding_id": finding_dict.get("finding_fingerprint"),
                        "adjustment": result.confidence_adjustment,
                        "status": "rejected",
                        "reason": result.reason
                    })
                    activity.logger.info(
                        f"Layer 3: REJECTED {category} in {finding_dict.get('file_path')} - {result.reason}"
                    )
                
                elif result.status == VerificationStatus.UNVERIFIED:
                    finding_dict["sandbox_verified"] = False
                    finding_dict["verification_reason"] = result.reason
                    unverified += 1
                    activity.logger.debug(
                        f"Layer 3: UNVERIFIED {category} - {result.reason}"
                    )
                
                else:  # SKIPPED
                    skipped += 1
            else:
                skipped += 1
        
        # Remove rejected findings from results
        findings_filtered = [f for f in findings if not f.get("_reject", False)]
        ar.findings_json = json.dumps(findings_filtered)
        ar.findings_count = len(findings_filtered)
    
    activity.logger.info(
        f"Layer 3 complete: {verified} verified, {rejected} rejected (false positives), "
        f"{unverified} unverified, {skipped} skipped"
    )
    
    return VerificationResult(
        verified_count=verified,
        rejected_count=rejected,
        unverified_count=unverified,
        skipped_count=skipped,
        confidence_adjustments=adjustments
    )
    
    # FUTURE: Full implementation
    # verifier = ExecutionVerifier(sandbox_client=docker_client, logger=activity.logger)
    # 
    # verified = 0
    # rejected = 0
    # unverified = 0
    # skipped = 0
    # adjustments = []
    # 
    # # Parse all findings
    # for ar in agent_results:
    #     findings = json.loads(ar.findings_json)
    #     
    #     for finding in findings:
    #         severity = finding.get("severity", "").lower()
    #         
    #         # Only verify critical/high findings
    #         if severity in ["critical", "high"]:
    #             result = await verifier.verify_finding(finding)
    #             
    #             if result.status == VerificationStatus.VERIFIED:
    #                 finding["confidence"] += result.confidence_adjustment
    #                 finding["sandbox_verified"] = True
    #                 verified += 1
    #                 adjustments.append({
    #                     "finding_id": finding.get("finding_fingerprint"),
    #                     "adjustment": result.confidence_adjustment,
    #                     "status": "verified"
    #                 })
    #             
    #             elif result.status == VerificationStatus.REJECTED:
    #                 # False positive - remove from results
    #                 rejected += 1
    #                 adjustments.append({
    #                     "finding_id": finding.get("finding_fingerprint"),
    #                     "adjustment": result.confidence_adjustment,
    #                     "status": "rejected"
    #                 })
    #             
    #             elif result.status == VerificationStatus.UNVERIFIED:
    #                 finding["sandbox_verified"] = False
    #                 unverified += 1
    #             
    #             else:
    #                 skipped += 1
    #         else:
    #             skipped += 1
    # 
    # activity.logger.info(
    #     "Layer 3 complete: %d verified, %d rejected, %d unverified, %d skipped",
    #     verified, rejected, unverified, skipped
    # )
    # 
    # return VerificationResult(
    #     verified_count=verified,
    #     rejected_count=rejected,
    #     unverified_count=unverified,
    #     skipped_count=skipped,
    #     confidence_adjustments=adjustments
    # )


@activity.defn
async def synthesize_findings(
    audit_input: AuditInput,
    agent_results: List[AgentResult],
) -> AuditSummary:
    """Merge, deduplicate, and cross-validate findings from all agents.

    Phase 3: Manager Synthesis
    Phase 4: Database Storage
    """
    import json
    from tron.infra.redis.pubsub import publish_progress, publish_audit_completed

    audit_run_id = UUID(audit_input.audit_run_id)

    await publish_progress(audit_run_id, "running", 80, "Synthesizing findings from all agents")

    # Collect all findings and any errors
    all_findings_dicts: List[Dict[str, Any]] = []
    agent_errors: List[str] = []
    threat_intel_alerts: List[str] = []

    for ar in agent_results:
        if ar.errors:
            error_msg = f"{ar.agent_id} failed: {', '.join(ar.errors)}"
            activity.logger.error(error_msg)
            agent_errors.append(error_msg)

        if ar.threat_intel_alerts:
            threat_intel_alerts.extend(ar.threat_intel_alerts)

        try:
            if ar.findings_json and ar.findings_json != "[]":
                findings = json.loads(ar.findings_json)
                all_findings_dicts.extend(findings)

        except json.JSONDecodeError:
            activity.logger.warning("Failed to parse findings from %s", ar.agent_id)

    # Deduplicate by fingerprint
    seen: Dict[str, Dict[str, Any]] = {}
    for f in all_findings_dicts:
        fp = f.get("finding_fingerprint", str(uuid4()))
        if fp not in seen:
            seen[fp] = f
        else:
            # Keep the one with tool confirmation or higher confidence
            existing = seen[fp]
            if f.get("deterministic_tool_confirmed") and not existing.get("deterministic_tool_confirmed"):
                seen[fp] = f
            elif f.get("confidence", 0) > existing.get("confidence", 0):
                seen[fp] = f

    deduped = list(seen.values())

    # Count severities
    sev_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in deduped:
        sev = f.get("severity", "medium")
        if sev in sev_counts:
            sev_counts[sev] += 1

    activity.logger.info(
        "Synthesis: %d raw → %d deduped (%d critical, %d high)",
        len(all_findings_dicts),
        len(deduped),
        sev_counts["critical"],
        sev_counts["high"],
    )

    await publish_progress(audit_run_id, "running", 90, "Persisting findings to database")

    # Persist to database
    await _persist_findings_to_db(audit_input, deduped)

    # Finalize audit run
    total_duration = sum(ar.duration_seconds for ar in agent_results)
    await _finalize_audit_run(audit_input, deduped, sev_counts, total_duration, threat_intel_alerts)

    # Publish completion
    await publish_audit_completed(
        audit_run_id,
        findings_total=len(deduped),
        findings_critical=sev_counts["critical"],
        findings_high=sev_counts["high"],
        findings_medium=sev_counts["medium"],
        findings_low=sev_counts["low"],
        duration_seconds=total_duration,
    )

    from tron.services.agent_handoff import maybe_write_agent_handoff_after_audit

    await maybe_write_agent_handoff_after_audit(
        audit_run_id=audit_run_id,
        project_id=UUID(audit_input.project_id),
        preloaded_findings=deduped,
    )

    return AuditSummary(
        audit_run_id=audit_input.audit_run_id,
        findings_total=len(deduped),
        findings_critical=sev_counts["critical"],
        findings_high=sev_counts["high"],
        findings_medium=sev_counts["medium"],
        findings_low=sev_counts["low"],
        duration_seconds=total_duration,
        agents_run=len(agent_results),
        errors=agent_errors,
    )


@activity.defn
async def generate_fix(finding_input: FindingInput, iteration: int) -> FixAttempt:
    """Generate a code fix for a finding using the LLM.

    FixWorkflow Phase: Generate
    """
    from tron.infra.llm.client import LLMClient, LLMMessage, LLMRequest
    from tron.workflows._worker_state import get_worker_secrets

    secrets = get_worker_secrets()
    llm = LLMClient(
        anthropic_key=secrets.get("llm/anthropic-key"),
        openai_key=secrets.get("llm/openai-key"),
    )

    from tron.infra.llm.usage_context import (
        LLMUsageRecordContext,
        get_activity_workflow_ids,
        llm_usage_scope,
    )

    _wf_id, _run_id = get_activity_workflow_ids()
    _fix_ctx = LLMUsageRecordContext(
        project_id=UUID(finding_input.project_id),
        workflow_id=_wf_id,
        workflow_run_id=_run_id,
        operation_mode="fix",
        operation_detail="generate_fix",
    )

    prompt = (
        f"Fix this {finding_input.vulnerability_type} vulnerability.\n\n"
        f"File: {finding_input.file_path}\n"
        f"Line: {finding_input.line_number}\n"
        f"Severity: {finding_input.severity}\n"
        f"Description: {finding_input.description}\n\n"
        f"Current code:\n```\n{finding_input.code_snippet}\n```\n\n"
        f"Provide ONLY the fixed code. No explanations, just the corrected code "
        f"that replaces the vulnerable section."
    )

    if iteration > 1:
        prompt += (
            f"\n\nThis is attempt #{iteration}. Previous fix attempts failed verification. "
            f"Ensure the fix fully addresses the vulnerability without breaking functionality."
        )

    try:
        with llm_usage_scope(_fix_ctx):
            response = await llm.complete(LLMRequest(
                messages=[
                    LLMMessage(
                        role="system",
                        content="You are a security engineer. Fix the vulnerability. "
                        "Return ONLY the corrected code, no explanations.",
                    ),
                    LLMMessage(role="user", content=prompt),
                ],
                model=DEFAULT_ANTHROPIC_FAST_MODEL,
                temperature=0.1,
                max_tokens=2000,
            ))

        fix_code = response.content.strip()
        # Strip markdown code blocks if present
        if fix_code.startswith("```"):
            lines = fix_code.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            fix_code = "\n".join(lines).strip()

        return FixAttempt(
            iteration=iteration,
            fix_code=fix_code,
            verification_passed=False,  # Will be verified in next activity
            verification_output="",
        )

    except Exception as exc:
        return FixAttempt(
            iteration=iteration,
            fix_code="",
            verification_passed=False,
            verification_output="",
            error_message=str(exc),
        )
    finally:
        await llm.close()


def _language_from_file_path(file_path: str) -> str:
    p = (file_path or "").lower()
    if p.endswith(".py"):
        return "python"
    if p.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")):
        return "javascript"
    return "python"


@activity.defn
async def verify_fix(finding_input: FindingInput, fix_attempt: FixAttempt) -> FixAttempt:
    """Verify a fix: prefer sandbox execution (same service as audit Layer 3), else static heuristics."""
    import os

    if not fix_attempt.fix_code:
        return FixAttempt(
            iteration=fix_attempt.iteration,
            fix_code=fix_attempt.fix_code,
            verification_passed=False,
            verification_output="No fix code generated",
            error_message=fix_attempt.error_message,
        )

    fix_code = fix_attempt.fix_code
    vuln_type = finding_input.vulnerability_type
    lang = _language_from_file_path(finding_input.file_path)

    # ── Primary: remote sandbox (TRON_SANDBOX_URL) — execution parity with audit Layer 3 ──
    sandbox_url = os.environ.get("TRON_SANDBOX_URL", "").strip()
    if sandbox_url and lang == "python":
        from tron.infra.sandbox.http import HTTPSandbox

        http_sandbox = HTTPSandbox(sandbox_url=sandbox_url, timeout_seconds=60)
        try:
            if await http_sandbox.health_check():
                vr = await http_sandbox.verify_fix(
                    original_code=finding_input.code_snippet or "",
                    fixed_code=fix_code,
                    test_code="",
                    language=lang,
                )
                out = vr.summary
                if vr.test_output:
                    out = f"{out}. Output: {vr.test_output[:2000]}"
                if vr.errors:
                    out = f"{out}; " + "; ".join(vr.errors[:5])
                activity.logger.info(
                    "Verify fix (sandbox, iter %d): %s — %s",
                    fix_attempt.iteration,
                    "PASS" if vr.passed else "FAIL",
                    out[:500],
                )
                return FixAttempt(
                    iteration=fix_attempt.iteration,
                    fix_code=fix_code,
                    verification_passed=vr.passed,
                    verification_output=out[:8000],
                    error_message=fix_attempt.error_message,
                )
            activity.logger.warning(
                "Fix verify: sandbox unhealthy at %s — falling back to static checks",
                sandbox_url,
            )
        except Exception as exc:
            activity.logger.warning(
                "Fix verify: sandbox error (%s) — falling back to static checks",
                exc,
            )
        finally:
            await http_sandbox.close()

    # ── Fallback: static heuristics (non-Python or sandbox unavailable) ──
    issues: List[str] = []

    if vuln_type == "sql_injection":
        if "execute(" in fix_code and ("+ " in fix_code or "%" in fix_code or ".format(" in fix_code):
            issues.append("Fix still contains string concatenation in SQL query")

    elif vuln_type == "command_injection":
        if "shell=True" in fix_code:
            issues.append("Fix still uses shell=True in subprocess")

    elif vuln_type == "hardcoded_secrets":
        secret_patterns = ["password", "api_key", "secret", "token"]
        for pat in secret_patterns:
            if pat in fix_code.lower() and ("=" in fix_code) and ('"' in fix_code or "'" in fix_code):
                if "os.environ" not in fix_code and "getenv" not in fix_code and "config" not in fix_code.lower():
                    issues.append(f"Fix may still contain hardcoded {pat}")

    elif vuln_type == "insecure_deserialization":
        if "pickle.loads" in fix_code or "pickle.load(" in fix_code:
            issues.append("Fix still uses pickle deserialization")

    elif vuln_type == "xss":
        if "render_template_string" in fix_code and "escape" not in fix_code and "Markup" not in fix_code:
            issues.append("Fix may still be vulnerable to XSS")

    verification_passed = len(issues) == 0
    verification_output = (
        "PASS: Fix appears to address the vulnerability (static check)"
        if verification_passed
        else "; ".join(issues)
    )

    activity.logger.info(
        "Verify fix (static, iter %d): %s — %s",
        fix_attempt.iteration,
        "PASS" if verification_passed else "FAIL",
        verification_output,
    )

    return FixAttempt(
        iteration=fix_attempt.iteration,
        fix_code=fix_attempt.fix_code,
        verification_passed=verification_passed,
        verification_output=verification_output,
    )


@activity.defn
async def persist_fix(finding_input: FindingInput, fix_attempt: FixAttempt) -> str:
    """Persist a verified fix to the database.

    Returns the finding ID for tracking. Opening a host VCS PR is a separate
    product track and is not performed in this activity.
    """
    from sqlalchemy import update
    from tron.domain.models import Finding
    from tron.infra.db.session import _session_factory

    finding_id = UUID(finding_input.finding_id)

    async with _session_factory() as session:
        await session.execute(
            update(Finding)
            .where(Finding.id == finding_id)
            .values(
                status="fixed",
                suggested_fix=fix_attempt.fix_code,
                resolved_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    activity.logger.info("Fix persisted for finding %s", finding_id)
    return str(finding_id)


@activity.defn
async def escalate_to_human(finding_input: FindingInput, attempts: int) -> str:
    """Mark a finding for human review after max fix iterations.

    Returns a status message.
    """
    from sqlalchemy import update
    from tron.domain.models import Finding
    from tron.infra.db.session import _session_factory

    finding_id = UUID(finding_input.finding_id)

    async with _session_factory() as session:
        await session.execute(
            update(Finding)
            .where(Finding.id == finding_id)
            .values(
                status="needs_review",
                resolution=f"Auto-fix failed after {attempts} attempts",
            )
        )
        await session.commit()

    activity.logger.info(
        "Finding %s escalated to human after %d fix attempts",
        finding_id, attempts,
    )
    return f"Escalated finding {finding_id} after {attempts} attempts"


@activity.defn
async def generate_project_plan(job: PlanJobInput) -> PlanSummary:
    """PLAN mode: LLM-generated plan stored in projects.plan_artifact_json."""
    import json

    from sqlalchemy import select, update

    from tron.domain.models import Project
    from tron.infra.db.session import _session_factory
    from tron.infra.llm.client import LLMClient, LLMMessage, LLMRequest
    from tron.standards.engine import merge_quality_gates
    from tron.workflows._worker_state import get_worker_secrets

    secrets = get_worker_secrets()
    pid = UUID(job.project_id)
    async with _session_factory() as session:
        res = await session.execute(
            select(Project).where(Project.id == pid, Project.deleted_at.is_(None))
        )
        project = res.scalar_one_or_none()
        if not project:
            return PlanSummary(
                project_id=job.project_id, ok=False, message="project not found"
            )
        name = project.name
        repo = project.repo_url or ""
        default_branch = project.default_branch or "main"
        merged_gates = merge_quality_gates(
            project.quality_gates_json,
            company_override=project.company_quality_gates_json,
        )

    anthropic_key = secrets.get("llm/anthropic-key", "")
    model = (
        DEFAULT_ANTHROPIC_FAST_MODEL
        if anthropic_key and anthropic_key != "REPLACE_ME_IN_VAULT"
        else "gpt-4o-mini"
    )
    llm = LLMClient(
        anthropic_key=secrets.get("llm/anthropic-key"),
        openai_key=secrets.get("llm/openai-key"),
    )
    from tron.infra.llm.usage_context import (
        LLMUsageRecordContext,
        get_activity_workflow_ids,
        llm_usage_scope,
    )

    _pwf, _prun = get_activity_workflow_ids()
    _plan_ctx = LLMUsageRecordContext(
        project_id=pid,
        workflow_id=_pwf,
        workflow_run_id=_prun,
        operation_mode="plan",
        operation_detail="generate_project_plan",
    )
    from tron.services.plan_questionnaire import compile_plan_inputs

    eff_goals, eff_constraints = compile_plan_inputs(
        job.goals, job.constraints, job.questionnaire
    )
    q_block = ""
    if job.questionnaire:
        try:
            q_block = "\n\nStructured questionnaire (JSON):\n" + json.dumps(
                job.questionnaire, indent=2
            )
        except (TypeError, ValueError):
            q_block = ""

    user = f"""Project: {name}
Repository: {repo}

Goals:
{eff_goals}

Constraints:
{eff_constraints}
{q_block}

Return a single JSON object with keys:
architecture_summary (string),
requirements_bullets (array of strings),
quality_gates_suggested (object),
test_plan_outline (array of strings),
risks (array of strings).
No markdown, JSON only."""
    try:
        with llm_usage_scope(_plan_ctx):
            resp = await llm.complete(
                LLMRequest(
                    messages=[
                        LLMMessage(
                            role="system",
                            content="You are a principal engineer. Output ONLY valid JSON.",
                        ),
                        LLMMessage(role="user", content=user),
                    ],
                    model=model,
                    temperature=0.2,
                    max_tokens=4096,
                    json_mode=True,
                )
            )
        artifact = json.loads(resp.content.strip())
    except Exception as exc:
        activity.logger.exception("Plan generation failed: %s", exc)
        artifact = {"error": str(exc)[:2000]}
    finally:
        await llm.close()

    artifact["merged_default_gates"] = merged_gates
    artifact["questionnaire"] = job.questionnaire
    artifact["compiled_goals"] = eff_goals
    artifact["compiled_constraints"] = eff_constraints

    from tron.services.plan_artifacts import build_tron_plan_files_dict

    bundle = build_tron_plan_files_dict(
        project_id=str(pid),
        project_name=name,
        repo_url=repo,
        default_branch=default_branch,
        goals=eff_goals,
        constraints=eff_constraints,
        artifact=artifact,
        questionnaire=job.questionnaire,
    )
    artifact["tron_bundle_v1"] = bundle
    tron_written = list(bundle.keys())

    import os

    if job.write_tron_files and repo:
        token = os.environ.get("TRON_PLAN_GIT_TOKEN", "").strip()
        if token:
            try:
                from tron.services.git_plan_bundle import (
                    GitPlanBundleError,
                    push_tron_plan_bundle,
                )

                await push_tron_plan_bundle(
                    repo_url=repo,
                    branch=default_branch,
                    bundle=bundle,
                    token=token,
                )
                artifact["tron_git_push"] = "ok"
            except GitPlanBundleError as exc:
                activity.logger.warning("TRON plan git push failed: %s", exc)
                artifact["tron_git_push_error"] = str(exc)[:500]
        else:
            artifact["tron_git_push"] = "skipped_no_token"
    else:
        artifact["tron_git_push"] = "skipped_no_repo_or_disabled"

    async with _session_factory() as session:
        values: Dict[str, Any] = {"plan_artifact_json": artifact}
        if job.questionnaire is not None:
            values["plan_questionnaire_json"] = job.questionnaire
        await session.execute(
            update(Project).where(Project.id == pid).values(**values)
        )
        await session.commit()
    return PlanSummary(
        project_id=job.project_id,
        ok=True,
        message="plan saved",
        tron_files_written=tron_written,
    )


@activity.defn
async def evaluate_build_quality_gates(
    job: BuildJobInput, result: AgentResult
) -> BuildQualityGateEval:
    """Evaluate merged quality gates against builder findings (same engine as audit POST)."""
    import json

    from sqlalchemy import select

    from tron.domain.models import Project
    from tron.infra.db.session import _session_factory
    from tron.standards.engine import evaluate_quality_gates, merge_quality_gates

    pid = UUID(job.project_id)
    findings = json.loads(result.findings_json or "[]")
    crit = high = med = low = 0
    rows: List[Dict[str, Any]] = []
    for raw in findings:
        if not isinstance(raw, dict):
            continue
        sev = str(raw.get("severity", "")).lower()
        if "critical" in sev:
            crit += 1
        elif "high" in sev:
            high += 1
        elif "medium" in sev or "med" in sev:
            med += 1
        elif "low" in sev:
            low += 1
        vt = raw.get("vulnerability_type")
        rows.append(
            {
                "rule_id": str(vt) if vt is not None else "",
                "title": str(raw.get("description", ""))[:400],
                "category": str(raw.get("category", "")),
                "severity": sev,
            }
        )
    total = len(rows)

    async with _session_factory() as session:
        row = await session.scalar(select(Project).where(Project.id == pid))
        gates = merge_quality_gates(
            row.quality_gates_json if row else None,
            company_override=row.company_quality_gates_json if row else None,
        )
    passed, criteria = evaluate_quality_gates(
        gates,
        findings_total=total,
        findings_critical=crit,
        findings_high=high,
        findings_medium=med,
        findings_low=low,
        coverage_percent=None,
        finding_rows=rows,
    )
    return BuildQualityGateEval(passed=passed, criteria_json=json.dumps(criteria))


@activity.defn
async def run_build_repo_validation(meta: ProjectMeta) -> BuildValidationOutcome:
    """Run ``python -m compileall`` on a fresh clone (BUILD test gate)."""
    import asyncio
    import os
    import shutil
    import sys

    from tron.services.repo_scanner import RepoScanner, RepoScanError

    if not meta.repo_url:
        return BuildValidationOutcome(True, "skipped", 0, "no repo_url")

    token = os.getenv("TRON_BUILD_GIT_TOKEN") or os.getenv("TRON_PLAN_GIT_TOKEN")
    url = meta.repo_url.strip()
    if token and url.startswith("https://"):
        url = url.replace("https://", f"https://x-access-token:{token}@", 1)

    scanner = RepoScanner(max_files=2000, max_total_size=50 * 1024 * 1024)
    root = ""
    try:
        root = await scanner.clone_to_tempdir(url, meta.default_branch or "main")
    except RepoScanError as exc:
        return BuildValidationOutcome(False, "git_clone", -1, str(exc)[:2000])

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "compileall",
            "-q",
            "-f",
            ".",
            cwd=root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=300)
        tail = (err.decode("utf-8", errors="replace") or out.decode("utf-8", errors="replace"))[
            -4000:
        ]
        ok = proc.returncode == 0
        return BuildValidationOutcome(
            ok=ok,
            command="python -m compileall -q -f .",
            exit_code=int(proc.returncode or 0),
            log_tail=tail,
        )
    except asyncio.TimeoutError:
        return BuildValidationOutcome(
            False, "python -m compileall -q -f .", -1, "compileall timed out (300s)"
        )
    finally:
        if root:
            shutil.rmtree(root, ignore_errors=True)


@activity.defn
async def maybe_push_build_report_branch(
    job: BuildJobInput, artifact_json: str
) -> BuildGitPushOutcome:
    """Optional: push ``.tron/build-result.json`` to ``tron/build-<run>`` (TRON_BUILD_GIT_TOKEN)."""
    import os

    from sqlalchemy import select

    from tron.domain.models import Project
    from tron.infra.db.session import _session_factory
    from tron.services.git_build_report import GitBuildReportError, push_build_report_branch

    token = os.getenv("TRON_BUILD_GIT_TOKEN") or os.getenv("TRON_PLAN_GIT_TOKEN")
    if not token:
        return BuildGitPushOutcome(False, "", "skipped_no_token")

    pid = UUID(job.project_id)
    repo_url: str | None = None
    default_branch = "main"
    async with _session_factory() as session:
        row = await session.scalar(select(Project).where(Project.id == pid))
        if row:
            repo_url = row.repo_url
            default_branch = row.default_branch or "main"
    if not repo_url:
        return BuildGitPushOutcome(False, "", "skipped_no_repo")

    branch = f"tron/build-{job.build_run_id[:8]}"
    try:
        await push_build_report_branch(
            repo_url=repo_url,
            branch_default=default_branch,
            target_branch=branch,
            token=token,
            artifact_json=artifact_json,
        )
    except GitBuildReportError as exc:
        return BuildGitPushOutcome(True, branch, f"error:{exc!s}"[:2000])

    return BuildGitPushOutcome(True, branch, "pushed")


@activity.defn
async def save_build_result(
    job: BuildJobInput,
    result: AgentResult,
    gate_eval: BuildQualityGateEval,
    validation: BuildValidationOutcome,
) -> BuildSummary:
    """Persist BUILD mode ISO output plus gate + compileall validation on the project row."""
    import json

    from sqlalchemy import update

    from tron.domain.models import Project
    from tron.infra.db.session import _session_factory

    pid = UUID(job.project_id)
    criteria = json.loads(gate_eval.criteria_json or "[]")
    payload = {
        "task": job.task,
        "findings_count": result.findings_count,
        "findings": json.loads(result.findings_json or "[]"),
        "errors": result.errors,
        "duration_seconds": result.duration_seconds,
        "quality_gates_passed": gate_eval.passed,
        "quality_gate_criteria": criteria,
        "validation": {
            "ok": validation.ok,
            "command": validation.command,
            "exit_code": validation.exit_code,
            "log_tail": validation.log_tail,
        },
    }
    artifact_json = json.dumps(payload)
    async with _session_factory() as session:
        await session.execute(
            update(Project)
            .where(Project.id == pid)
            .values(last_build_result_json=payload)
        )
        await session.commit()
    overall_ok = gate_eval.passed and validation.ok and not result.errors
    return BuildSummary(
        project_id=job.project_id,
        findings_count=result.findings_count,
        ok=overall_ok,
        message="build result saved",
        artifact_json=artifact_json,
    )


@activity.defn
async def merge_build_git_metadata(
    job: BuildJobInput, git_out: BuildGitPushOutcome
) -> None:
    """Attach git push metadata to ``last_build_result_json``."""
    import json

    from sqlalchemy import select, update

    from tron.domain.models import Project
    from tron.infra.db.session import _session_factory

    pid = UUID(job.project_id)
    async with _session_factory() as session:
        row = await session.scalar(select(Project).where(Project.id == pid))
        if not row or not row.last_build_result_json:
            return
        base = dict(row.last_build_result_json) if isinstance(row.last_build_result_json, dict) else {}
        base["git"] = {
            "attempted": git_out.attempted,
            "branch": git_out.branch,
            "detail": git_out.detail,
        }
        await session.execute(
            update(Project).where(Project.id == pid).values(last_build_result_json=base)
        )
        await session.commit()


@activity.defn
async def save_evolve_result(job: EvolveJobInput, result: AgentResult) -> EvolveSummary:
    """Persist EVOLVE mode ISO output on the project row."""
    import json

    from sqlalchemy import update

    from tron.domain.models import Project
    from tron.infra.db.session import _session_factory

    pid = UUID(job.project_id)
    payload = {
        "directive": job.directive,
        "evolve_run_id": job.evolve_run_id,
        "findings_count": result.findings_count,
        "findings": json.loads(result.findings_json or "[]"),
        "errors": result.errors,
        "duration_seconds": result.duration_seconds,
    }
    async with _session_factory() as session:
        await session.execute(
            update(Project)
            .where(Project.id == pid)
            .values(evolve_artifact_json=payload)
        )
        await session.commit()
    ok = not result.errors
    return EvolveSummary(
        project_id=job.project_id,
        findings_count=result.findings_count,
        ok=ok,
        message="evolve result saved",
        evolve_run_id=job.evolve_run_id,
    )


async def _compliance_reference_for_project(project_id: UUID) -> str:
    """Merge project + env compliance pack ids into LLM context text."""
    import os

    from sqlalchemy import select

    from tron.domain.models import Project
    from tron.infra.db.session import _session_factory
    from tron.standards.control_packs import format_packs_for_prompt

    env_ids = [
        x.strip()
        for x in (os.environ.get("TRON_COMPLIANCE_PACKS") or "").split(",")
        if x.strip()
    ]
    ids: list[str] = []
    async with _session_factory() as session:
        row = await session.scalar(
            select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
        )
    if row and getattr(row, "compliance_control_pack_ids", None):
        raw = row.compliance_control_pack_ids
        if isinstance(raw, list):
            ids.extend(str(x) for x in raw)
    for e in env_ids:
        if e not in ids:
            ids.append(e)
    return format_packs_for_prompt(ids)


# ── Internal Helpers ──────────────────────────────────────────────────


async def _execute_iso_agent(
    *,
    audit_run_id: UUID,
    agent: Any,
    agent_id: str,
    specialization: str,
    audit_input: AuditInput,
    scan_result: ScanResult,
    config: Any,
    start: float,
) -> AgentResult:
    """Run blueprint + agent.execute under llm_usage_scope (caller sets scope)."""
    import json

    from tron.schemas.verification import Blueprint, BlueprintScope, VerificationMethod, VulnerabilityType
    from tron.infra.redis.pubsub import publish_audit_event, AuditEvent

    desc = f"{specialization.title()} analysis"
    if specialization == "builder" and getattr(audit_input, "build_task", None):
        desc = (
            f"{desc}\n\nPRIMARY BUILD TASK (execute against this codebase):\n"
            f"{audit_input.build_task}\n"
        )
    blueprint = Blueprint(
        id=f"{audit_input.audit_run_id}-{specialization}",
        name=f"{specialization.title()} Analysis",
        description=desc,
        scope=BlueprintScope(
            file_patterns=["*.*"],
            check_types=list(VulnerabilityType),
            languages=scan_result.languages,
        ),
        tools_required=list(config.tools_required),
        max_tokens=config.max_tokens,
        max_duration_seconds=config.max_duration_seconds,
        temperature=config.temperature,
        verification_method=VerificationMethod.DETERMINISTIC_CROSSCHECK,
    )

    import fnmatch
    
    filtered_files = {}
    for path, content in (scan_result.file_contents or {}).items():
        # Check if included
        included = False
        for pat in blueprint.scope.file_patterns:
            if fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(path, f"*/{pat}"):
                included = True
                break
        
        # Check if excluded
        if included and blueprint.not_in_scope:
            for pat in blueprint.not_in_scope:
                if fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(path, f"*/{pat}"):
                    included = False
                    break
                    
        if included:
            filtered_files[path] = content

    all_files = filtered_files
    file_budget = config.max_tokens - 1500
    total_tokens_est = sum(len(c) // 4 for c in all_files.values())
    max_batches = 5

    if total_tokens_est <= file_budget:
        batch = await agent.execute(
            blueprint=blueprint,
            file_contents=all_files,
        )
        all_findings = list(batch.findings)
    else:
        activity.logger.info(
            "Multi-batch mode: %d tokens across %d files (budget=%d/batch, up to %d batches)",
            total_tokens_est, len(all_files), file_budget, max_batches,
        )
        all_findings = []
        remaining_files = dict(all_files)
        batch_num = 0
        while remaining_files and batch_num < max_batches:
            batch_num += 1
            batch = await agent.execute(
                blueprint=blueprint,
                file_contents=remaining_files,
            )
            all_findings.extend(batch.findings)
            included = agent._truncate_to_budget(
                remaining_files, max(file_budget, 500)
            )
            for path in included:
                remaining_files.pop(path, None)
            activity.logger.info(
                "Batch %d/%d: scanned %d files, found %d findings, %d files remaining",
                batch_num, max_batches, len(included), len(batch.findings), len(remaining_files),
            )
            if not remaining_files:
                break

        seen_fps = set()
        deduped = []
        for f in all_findings:
            fp = (
                getattr(f, "finding_fingerprint", None)
                or getattr(f, "fingerprint", None)
                or str(uuid4())
            )
            if fp not in seen_fps:
                seen_fps.add(fp)
                deduped.append(f)
        all_findings = deduped

    findings_dicts = [f.model_dump(mode="json") for f in all_findings]
    for fd in findings_dicts:
        fd["id"] = str(fd["id"])

    duration = time.time() - start
    metrics = agent.metrics

    await publish_audit_event(
        audit_run_id, AuditEvent.AGENT_COMPLETED,
        {
            "agent_id": agent_id,
            "specialization": specialization,
            "findings_count": len(all_findings),
            "duration_seconds": round(duration, 1),
        },
    )

    return AgentResult(
        agent_id=agent_id,
        specialization=specialization,
        findings_count=len(all_findings),
        findings_json=json.dumps(findings_dicts),
        duration_seconds=round(duration, 1),
        llm_tokens_used=metrics.llm_tokens_used if metrics else 0,
        llm_cost_usd=metrics.llm_cost_usd if metrics else 0.0,
        errors=metrics.errors if metrics else [],
        threat_intel_alerts=metrics.threat_intel_alerts if metrics else [],
    )


async def _run_agent(
    audit_input: AuditInput,
    scan_result: ScanResult,
    specialization: str,
    agent_id: str,
) -> AgentResult:
    """Shared logic for running any ISO agent as a Temporal activity."""
    from tron.agents.base import ISOConfig, ISOSpecialization, LLMProvider
    from tron.agents.builder_iso import BuilderISO
    from tron.agents.compliance_iso import ComplianceISO
    from tron.agents.documentation_iso import DocumentationISO
    from tron.agents.performance_iso import PerformanceISO
    from tron.agents.qa_iso import QAISO
    from tron.agents.security_iso import SecurityISO
    from tron.infra.llm.client import LLMClient
    from tron.infra.redis.pubsub import publish_audit_event, AuditEvent
    from tron.workflows._worker_state import get_worker_secrets

    import json as _json
    from tron.infra.redis.client import get_redis

    secrets = get_worker_secrets()
    audit_run_id = UUID(audit_input.audit_run_id)
    start = time.time()

    # Hydrate file_contents from Redis if not already present
    if scan_result.file_contents is None and scan_result.redis_key:
        redis = get_redis()
        raw = await redis.get(scan_result.redis_key)
        if raw:
            scan_result.file_contents = _json.loads(raw)
            activity.logger.info(
                "Loaded %d files from Redis (%s)",
                len(scan_result.file_contents), scan_result.redis_key,
            )
        else:
            activity.logger.error("Redis key %s expired or missing", scan_result.redis_key)
            scan_result.file_contents = {}

    # Select provider
    anthropic_key = secrets.get("llm/anthropic-key", "")
    if anthropic_key and anthropic_key != "REPLACE_ME_IN_VAULT":
        provider = LLMProvider.ANTHROPIC
        model = DEFAULT_ANTHROPIC_FAST_MODEL
    else:
        provider = LLMProvider.OPENAI
        model = "gpt-4o"

    llm = LLMClient(
        anthropic_key=secrets.get("llm/anthropic-key"),
        openai_key=secrets.get("llm/openai-key"),
    )

    # Map specialization to agent class
    spec_enum = ISOSpecialization(specialization)
    agent_classes = {
        ISOSpecialization.SECURITY: SecurityISO,
        ISOSpecialization.BUILDER: BuilderISO,
        ISOSpecialization.PERFORMANCE: PerformanceISO,
        ISOSpecialization.QA: QAISO,
        ISOSpecialization.COMPLIANCE: ComplianceISO,
        ISOSpecialization.DOCUMENTATION: DocumentationISO,
    }

    agent_cls = agent_classes.get(spec_enum)
    if not agent_cls:
        return AgentResult(
            agent_id=agent_id,
            specialization=specialization,
            findings_count=0,
            findings_json="[]",
            duration_seconds=0.0,
            llm_tokens_used=0,
            llm_cost_usd=0.0,
            errors=[f"Unknown specialization: {specialization}"],
        )

    cref = ""
    if specialization == "compliance":
        cref = await _compliance_reference_for_project(UUID(audit_input.project_id))

    config = ISOConfig(
        specialization=spec_enum,
        agent_id=agent_id,
        model_provider=provider,
        model_name=model,
        temperature=0.1,
        max_tokens=32000,   # Haiku supports 200K context; send more files for thorough analysis
        max_duration_seconds=300,
        tools_required=("bandit", "semgrep") if specialization == "security" else (),
        prompt_template_id=f"{specialization}-v1",
        compliance_reference_context=cref,
    )

    agent = agent_cls(config=config, secrets=secrets, llm_client=llm)

    # Publish start event
    await publish_audit_event(
        audit_run_id, AuditEvent.AGENT_STARTED,
        {"agent_id": agent_id, "specialization": specialization, "model": model},
    )

    from tron.infra.llm.usage_context import (
        LLMUsageRecordContext,
        get_activity_workflow_ids,
        llm_usage_scope,
    )

    _mode = "build" if (audit_input.triggered_by or "") == "build" else "audit"
    _wf_id, _run_id = get_activity_workflow_ids()
    _usage_ctx = LLMUsageRecordContext(
        project_id=UUID(audit_input.project_id),
        workflow_id=_wf_id,
        workflow_run_id=_run_id,
        operation_mode=_mode,
        operation_detail=f"iso:{specialization}",
    )

    try:
        with llm_usage_scope(_usage_ctx):
            return await _execute_iso_agent(
                audit_run_id=audit_run_id,
                agent=agent,
                agent_id=agent_id,
                specialization=specialization,
                audit_input=audit_input,
                scan_result=scan_result,
                config=config,
                start=start,
            )

    except Exception as exc:
        activity.logger.exception("Agent %s failed: %s", agent_id, exc)
        return AgentResult(
            agent_id=agent_id,
            specialization=specialization,
            findings_count=0,
            findings_json="[]",
            duration_seconds=time.time() - start,
            llm_tokens_used=0,
            llm_cost_usd=0.0,
            errors=[str(exc)],
        )
    finally:
        await llm.close()


async def _persist_findings_to_db(
    audit_input: AuditInput,
    findings: List[Dict[str, Any]],
) -> None:
    """Write findings to the database."""
    from tron.domain.models import Finding
    from tron.infra.db.session import _session_factory

    if not findings:
        return

    audit_run_id = UUID(audit_input.audit_run_id)
    project_id = UUID(audit_input.project_id)

    async with _session_factory() as session:
        for f in findings:
            finding = Finding(
                audit_run_id=audit_run_id,
                project_id=project_id,
                fingerprint=f.get("finding_fingerprint", str(uuid4())),
                rule_id=f.get("vulnerability_type", "other"),
                file_path=f.get("file_path", "unknown"),
                line_start=f.get("line_number", 1),
                line_end=f.get("line_end"),
                severity=f.get("severity", "medium"),
                category=f.get("vulnerability_type", "other"),
                title=f"{f.get('vulnerability_type', 'other')}: {f.get('file_path', '?')}:{f.get('line_number', '?')}",
                description=f.get("description", ""),
                suggested_fix=f.get("fix_suggestion"),
                status="open",
                code_snippet=f.get("code_snippet"),
            )
            session.add(finding)
        await session.commit()

    activity.logger.info("Persisted %d findings", len(findings))


async def _finalize_audit_run(
    audit_input: AuditInput,
    findings: List[Dict[str, Any]],
    sev_counts: Dict[str, int],
    duration: float,
    threat_intel_alerts: Optional[List[str]] = None,
) -> None:
    """Update the audit run record with final results."""
    from sqlalchemy import update
    from tron.domain.models import AuditRun
    from tron.infra.db.session import _session_factory

    audit_run_id = UUID(audit_input.audit_run_id)

    async with _session_factory() as session:
        await session.execute(
            update(AuditRun)
            .where(AuditRun.id == audit_run_id)
            .values(
                status="completed",
                progress=100,
                findings_total=len(findings),
                findings_critical=sev_counts.get("critical", 0),
                findings_high=sev_counts.get("high", 0),
                findings_medium=sev_counts.get("medium", 0),
                findings_low=sev_counts.get("low", 0),
                threat_intel_alerts_json=threat_intel_alerts,
                completed_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()


def _demo_source_files() -> Dict[str, str]:
    """Fallback demo app for projects without a repo_url."""
    return {"app.py": '''\
import os, subprocess, sqlite3, pickle, hashlib
from flask import Flask, request, render_template_string

app = Flask(__name__)
DATABASE_PASSWORD = "super_secret_password_123"

@app.route("/search")
def search():
    query = request.args.get("q", "")
    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE name = '" + query + "'")
    return str(cursor.fetchall())

@app.route("/run")
def run_command():
    cmd = request.args.get("cmd", "ls")
    output = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE)
    return output.stdout.read()

@app.route("/template")
def template():
    name = request.args.get("name", "World")
    return render_template_string("<h1>Hello " + name + "!</h1>")

@app.route("/load")
def load_data():
    return str(pickle.loads(request.get_data()))

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
'''}
