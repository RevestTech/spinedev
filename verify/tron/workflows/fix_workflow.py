"""
FixWorkflow — Durable Temporal workflow for auto-fixing findings.

Iterative loop (max 3 attempts):
  1. Generate fix (LLM)
  2. Verify fix (static analysis; sandbox in Phase 3)
  3. If pass → persist fix + create PR → done
  4. If fail → refine prompt, loop back to step 1
  5. After max iterations → escalate to human review

Each iteration is a separate Temporal activity, so progress survives
worker restarts. The workflow emits progress events via Redis pub/sub.

Architecture ref: docs/architecture/AI_AGENT_ARCHITECTURE.md §5
"""

from __future__ import annotations

import logging
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from tron.workflows.activities import (
        FindingInput,
        FixAttempt,
        FixResult,
        generate_fix,
        verify_fix,
        persist_fix,
        escalate_to_human,
    )

logger = logging.getLogger(__name__)

MAX_FIX_ITERATIONS = 3

_FIX_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=2,
)

_QUICK_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=15),
    maximum_attempts=3,
)


@workflow.defn
class FixWorkflow:
    """Iterative auto-fix workflow for a single finding.

    Accepts a FindingInput and returns a FixResult indicating
    whether the fix succeeded or was escalated to human review.
    """

    @workflow.run
    async def run(self, finding_input: FindingInput) -> FixResult:
        workflow.logger.info(
            "FixWorkflow started: finding=%s type=%s severity=%s",
            finding_input.finding_id,
            finding_input.vulnerability_type,
            finding_input.severity,
        )

        for iteration in range(1, MAX_FIX_ITERATIONS + 1):
            workflow.logger.info(
                "Fix iteration %d/%d for finding %s",
                iteration, MAX_FIX_ITERATIONS, finding_input.finding_id,
            )

            # Step 1: Generate fix
            attempt: FixAttempt = await workflow.execute_activity(
                generate_fix,
                args=[finding_input, iteration],
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=_FIX_RETRY,
            )

            if attempt.error_message:
                workflow.logger.warning(
                    "Fix generation failed (iter %d): %s",
                    iteration, attempt.error_message,
                )
                continue

            # Step 2: Verify fix
            verified: FixAttempt = await workflow.execute_activity(
                verify_fix,
                args=[finding_input, attempt],
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=_QUICK_RETRY,
            )

            if verified.verification_passed:
                workflow.logger.info(
                    "Fix verified on iteration %d for finding %s",
                    iteration, finding_input.finding_id,
                )

                # Step 3: Persist fix
                await workflow.execute_activity(
                    persist_fix,
                    args=[finding_input, verified],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=_QUICK_RETRY,
                )

                return FixResult(
                    finding_id=finding_input.finding_id,
                    success=True,
                    iterations_completed=iteration,
                    final_fix=verified.fix_code,
                    pr_url=None,  # Host PR creation is not implemented; fix is persisted on the finding
                )

            workflow.logger.info(
                "Fix failed verification (iter %d): %s",
                iteration, verified.verification_output,
            )

        # Exhausted all iterations — escalate to human
        workflow.logger.warning(
            "Fix failed after %d iterations for finding %s — escalating",
            MAX_FIX_ITERATIONS, finding_input.finding_id,
        )

        escalation_msg: str = await workflow.execute_activity(
            escalate_to_human,
            args=[finding_input, MAX_FIX_ITERATIONS],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_QUICK_RETRY,
        )

        return FixResult(
            finding_id=finding_input.finding_id,
            success=False,
            iterations_completed=MAX_FIX_ITERATIONS,
            error_message=escalation_msg,
        )
