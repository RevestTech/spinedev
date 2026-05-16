"""PlanWorkflow — proposal PLAN mode (artifact persisted on project)."""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from tron.workflows.activities import (
        PlanJobInput,
        PlanSummary,
        generate_project_plan,
    )

_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=60),
    maximum_attempts=2,
)


@workflow.defn
class PlanWorkflow:
    @workflow.run
    async def run(self, job: PlanJobInput) -> PlanSummary:
        workflow.logger.info("PlanWorkflow started for project %s", job.project_id)
        return await workflow.execute_activity(
            generate_project_plan,
            job,
            start_to_close_timeout=timedelta(minutes=8),
            retry_policy=_RETRY,
        )
