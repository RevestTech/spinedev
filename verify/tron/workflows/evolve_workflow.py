"""EvolveWorkflow — proposal EVOLVE mode (iterative improvement via Builder ISO)."""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from tron.workflows.activities import (
        AuditInput,
        EvolveJobInput,
        EvolveSummary,
        load_project_metadata,
        run_builder_agent,
        save_evolve_result,
        scan_repository,
    )

_AGENT = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=2),
    maximum_attempts=2,
)
_QUICK = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=3,
)


@workflow.defn
class EvolveWorkflow:
    @workflow.run
    async def run(self, job: EvolveJobInput) -> EvolveSummary:
        workflow.logger.info(
            "EvolveWorkflow started project=%s run=%s", job.project_id, job.evolve_run_id
        )
        audit_input = AuditInput(
            audit_run_id=job.evolve_run_id,
            project_id=job.project_id,
            triggered_by="evolve",
            scope="quality",
            build_task=(
                "EVOLVE pass — propose concrete incremental improvements, refactors, "
                "and risk reductions aligned with the directive below. Prioritize "
                "actionable engineering tasks.\n\nDIRECTIVE:\n"
                + job.directive
            ),
        )
        meta = await workflow.execute_activity(
            load_project_metadata,
            audit_input,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_QUICK,
        )
        scan = await workflow.execute_activity(
            scan_repository,
            meta,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=_QUICK,
        )
        agent_result = await workflow.execute_activity(
            run_builder_agent,
            args=[audit_input, scan],
            start_to_close_timeout=timedelta(minutes=12),
            retry_policy=_AGENT,
        )
        summary = await workflow.execute_activity(
            save_evolve_result,
            args=[job, agent_result],
            start_to_close_timeout=timedelta(seconds=90),
            retry_policy=_QUICK,
        )
        return summary
