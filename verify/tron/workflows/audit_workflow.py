"""
AuditWorkflow — Durable Temporal workflow for running a full Tron audit.

Orchestrates the 7-layer verification pipeline:
  Phase 1: Context Gathering — load project, scan repository

  Phase 2: Parallel ISO Analysis — security, builder, performance agents
    Layer 1: Deterministic Tools First (Bandit, Semgrep - inside agents)
    Layer 2: Schema-Enforced Output (Pydantic validation - inside agents)

  Phase 2.5: Execution Verification
    Layer 3: Sandbox Verification (test exploits in Docker sandbox)

  Phase 3: Manager Synthesis
    Layer 4: Multi-Agent Cross-Validation (merge, deduplicate)
    Layer 5: Blueprint-Scoped Tasks (standards hierarchy - future)
    Layer 6: Calibrated Confidence (golden test suite - future)
    Layer 7: Prompt Regression Testing (nightly regression - future)

  Phase 4: Database Storage — persist findings (inside synthesize_findings)
  Phase 5: Events — publish completion via Redis pub/sub

If any activity fails after retries, the workflow records ``failed`` in Postgres
via ``mark_audit_run_failed`` and re-raises so Temporal retains failure state.

Architecture ref: docs/architecture/ZERO_DRIFT_VERIFICATION_PIPELINE.md
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import List

from temporalio import workflow
from temporalio.common import RetryPolicy

# Import dataclasses (these are pure data, safe for workflow sandbox)
with workflow.unsafe.imports_passed_through():
    from tron.workflows.activities import (
        AuditInput,
        AuditSummary,
        AgentResult,
        ProjectMeta,
        ScanResult,
        VerificationResult,
        load_project_metadata,
        scan_repository,
        run_security_agent,
        run_builder_agent,
        run_performance_agent,
        run_qa_agent,
        run_compliance_agent,
        run_documentation_agent,
        verify_findings_with_sandbox,
        deep_verify_follow_up_findings,
        synthesize_findings,
        mark_audit_run_failed,
    )

logger = logging.getLogger(__name__)

# ── Retry policies ────────────────────────────────────────────────────
# Short-lived activities (DB reads) get fewer retries.
# Long-running activities (LLM agents) get more slack.

_QUICK_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=3,
)

_AGENT_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=60),
    maximum_attempts=2,  # LLM calls are expensive; don't over-retry
)

_SCAN_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=60),
    maximum_attempts=3,
)


@workflow.defn
class AuditWorkflow:
    """Durable audit pipeline executed by Temporal.

    Accepts an AuditInput and returns an AuditSummary.
    All state is persisted in Temporal's event history, so if the worker
    crashes mid-audit the workflow resumes from the last completed activity.
    """

    @workflow.run
    async def run(self, audit_input: AuditInput) -> AuditSummary:
        workflow.logger.info(
            "AuditWorkflow started: run=%s project=%s scope=%s",
            audit_input.audit_run_id,
            audit_input.project_id,
            audit_input.scope,
        )

        try:
            return await self._run_audit_phases(audit_input)
        except Exception as exc:
            import traceback
            from temporalio import exceptions as temp_exc
            
            # Extract underlying cause if it's a Temporal ActivityError
            cause = exc
            while isinstance(cause, (temp_exc.ActivityError, temp_exc.ChildWorkflowError)) and cause.__cause__:
                cause = cause.__cause__
            
            msg = f"{type(cause).__name__}: {cause}"[:900]
            stack = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            
            workflow.logger.error("AuditWorkflow failed: %s", msg)
            try:
                await workflow.execute_activity(
                    mark_audit_run_failed,
                    args=[audit_input.audit_run_id, msg, stack],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=_QUICK_RETRY,
                )
            except Exception as mark_exc:
                workflow.logger.error(
                    "mark_audit_run_failed activity failed: %s", mark_exc
                )
            raise

    async def _run_audit_phases(self, audit_input: AuditInput) -> AuditSummary:
        # ── Phase 1: Context Gathering ────────────────────────────────
        project_meta: ProjectMeta = await workflow.execute_activity(
            load_project_metadata,
            audit_input,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_QUICK_RETRY,
        )

        scan_result: ScanResult = await workflow.execute_activity(
            scan_repository,
            project_meta,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=_SCAN_RETRY,
        )

        workflow.logger.info(
            "Phase 1 complete: %d files, %s",
            scan_result.file_count,
            scan_result.languages,
        )

        # ── Phase 2: Parallel ISO Analysis ────────────────────────────
        agent_tasks = []

        if audit_input.scope in ("full", "security"):
            agent_tasks.append(
                workflow.execute_activity(
                    run_security_agent,
                    args=[audit_input, scan_result],
                    start_to_close_timeout=timedelta(minutes=10),
                    retry_policy=_AGENT_RETRY,
                )
            )

        if audit_input.scope in ("full", "quality"):
            agent_tasks.append(
                workflow.execute_activity(
                    run_builder_agent,
                    args=[audit_input, scan_result],
                    start_to_close_timeout=timedelta(minutes=10),
                    retry_policy=_AGENT_RETRY,
                )
            )

        if audit_input.scope in ("full", "performance"):
            agent_tasks.append(
                workflow.execute_activity(
                    run_performance_agent,
                    args=[audit_input, scan_result],
                    start_to_close_timeout=timedelta(minutes=10),
                    retry_policy=_AGENT_RETRY,
                )
            )

        if audit_input.scope == "full":
            agent_tasks.append(
                workflow.execute_activity(
                    run_qa_agent,
                    args=[audit_input, scan_result],
                    start_to_close_timeout=timedelta(minutes=10),
                    retry_policy=_AGENT_RETRY,
                )
            )
            agent_tasks.append(
                workflow.execute_activity(
                    run_compliance_agent,
                    args=[audit_input, scan_result],
                    start_to_close_timeout=timedelta(minutes=10),
                    retry_policy=_AGENT_RETRY,
                )
            )
            agent_tasks.append(
                workflow.execute_activity(
                    run_documentation_agent,
                    args=[audit_input, scan_result],
                    start_to_close_timeout=timedelta(minutes=10),
                    retry_policy=_AGENT_RETRY,
                )
            )

        agent_results: List[AgentResult] = await asyncio.gather(*agent_tasks)

        total_findings = sum(ar.findings_count for ar in agent_results)
        workflow.logger.info(
            "Phase 2 complete: %d agents, %d raw findings",
            len(agent_results),
            total_findings,
        )

        # ── Phase 2.5: Layer 3 - Execution Verification ───────────────
        verification_result: VerificationResult = await workflow.execute_activity(
            verify_findings_with_sandbox,
            args=[audit_input, agent_results],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=_QUICK_RETRY,
        )

        workflow.logger.info(
            "Layer 3 complete: %d verified, %d rejected (false positives), "
            "%d unverified, %d skipped",
            verification_result.verified_count,
            verification_result.rejected_count,
            verification_result.unverified_count,
            verification_result.skipped_count,
        )

        # ── Phase 2.6: SEC-5 optional second sandbox pass (top-N unverified) ──
        await workflow.execute_activity(
            deep_verify_follow_up_findings,
            args=[audit_input, agent_results],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=_QUICK_RETRY,
        )

        # ── Phase 3-5: Synthesis + Storage + Events ───────────────────
        summary: AuditSummary = await workflow.execute_activity(
            synthesize_findings,
            args=[audit_input, agent_results],
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=_QUICK_RETRY,
        )

        workflow.logger.info(
            "AuditWorkflow completed: %d findings "
            "(%d critical, %d high) in %.1fs",
            summary.findings_total,
            summary.findings_critical,
            summary.findings_high,
            summary.duration_seconds,
        )

        return summary
