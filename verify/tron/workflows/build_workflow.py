"""BuildWorkflow — proposal BUILD mode (builder ISO + task, result on project)."""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from tron.workflows.activities import (
        AuditInput,
        BuildJobInput,
        BuildSummary,
        evaluate_build_quality_gates,
        load_project_metadata,
        merge_build_git_metadata,
        maybe_push_build_report_branch,
        run_build_repo_validation,
        run_builder_agent,
        save_build_result,
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
class BuildWorkflow:
    @workflow.run
    async def run(self, job: BuildJobInput) -> BuildSummary:
        workflow.logger.info(
            "BuildWorkflow started project=%s run=%s", job.project_id, job.build_run_id
        )
        audit_input = AuditInput(
            audit_run_id=job.build_run_id,
            project_id=job.project_id,
            triggered_by="build",
            scope="quality",
            build_task=job.task,
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
        gate_eval = await workflow.execute_activity(
            evaluate_build_quality_gates,
            args=[job, agent_result],
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=_QUICK,
        )
        validation = await workflow.execute_activity(
            run_build_repo_validation,
            meta,
            start_to_close_timeout=timedelta(minutes=6),
            retry_policy=_QUICK,
        )
        summary = await workflow.execute_activity(
            save_build_result,
            args=[job, agent_result, gate_eval, validation],
            start_to_close_timeout=timedelta(seconds=90),
            retry_policy=_QUICK,
        )
        git_out = await workflow.execute_activity(
            maybe_push_build_report_branch,
            args=[job, summary.artifact_json],
            start_to_close_timeout=timedelta(minutes=8),
            retry_policy=_QUICK,
        )
        await workflow.execute_activity(
            merge_build_git_metadata,
            args=[job, git_out],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_QUICK,
        )
        return summary
