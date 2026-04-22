"""
Tron Temporal Worker entry point.

Connects to Temporal and registers workflow/activity handlers.
Secrets loaded from keyvault at startup and stored in _worker_state
so activities can access them without repeated keyvault calls.

Usage:
    python -m tron.worker
"""

from __future__ import annotations

import asyncio
import logging
import signal

from temporalio.client import Client
from temporalio.worker import Worker

from tron.api.config import settings
from tron.infra.db.session import init_db, close_db
from tron.infra.redis.client import init_redis, close_redis
from tron.infra.secrets import get_secret, get_secrets, merge_anthropic_key_aliases
from tron.workflows._worker_state import init_worker_state
from tron.workflows.audit_workflow import AuditWorkflow
from tron.workflows.build_workflow import BuildWorkflow
from tron.workflows.evolve_workflow import EvolveWorkflow
from tron.workflows.fix_workflow import FixWorkflow
from tron.workflows.plan_workflow import PlanWorkflow
from tron.workflows.activities import (
    load_project_metadata,
    scan_repository,
    run_security_agent,
    run_builder_agent,
    run_performance_agent,
    run_qa_agent,
    run_compliance_agent,
    run_documentation_agent,
    verify_findings_with_sandbox,
    synthesize_findings,
    mark_audit_run_failed,
    generate_fix,
    verify_fix,
    persist_fix,
    escalate_to_human,
    generate_project_plan,
    evaluate_build_quality_gates,
    merge_build_git_metadata,
    maybe_push_build_report_branch,
    run_build_repo_validation,
    save_build_result,
    save_evolve_result,
)

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    logger.info("Tron Worker starting up...")

    # ── Load secrets from keyvault ────────────────────────────────────
    secrets = await get_secrets([
        "db/password",
        "redis/password",
        "llm/openai-key",
        "llm/anthropic-key",
    ])
    try:
        secrets["anthropic-key"] = await get_secret("anthropic-key")
    except KeyError:
        pass
    secrets = merge_anthropic_key_aliases(secrets)
    logger.info("Secrets loaded from keyvault.")

    # Store secrets in worker-level state so activities can access them
    init_worker_state(secrets)
    logger.info("Worker state initialized.")

    # ── Initialize database ───────────────────────────────────────────
    db_url = settings.database_url(secrets["db/password"])
    await init_db(url=db_url, pool_size=5, max_overflow=2)
    logger.info("Database connected.")

    # ── Initialize Redis ──────────────────────────────────────────────
    redis_url = settings.redis_url(secrets["redis/password"])
    await init_redis(url=redis_url, pool_size=20)
    logger.info("Redis connected.")

    # ── Connect to Temporal ───────────────────────────────────────────
    temporal_client = await Client.connect(settings.temporal_host)
    logger.info("Temporal client connected: %s", settings.temporal_host)

    # ── Start Temporal worker ─────────────────────────────────────────
    worker = Worker(
        temporal_client,
        task_queue=settings.temporal_task_queue,
        workflows=[
            AuditWorkflow,
            FixWorkflow,
            PlanWorkflow,
            BuildWorkflow,
            EvolveWorkflow,
        ],
        activities=[
            # Audit pipeline activities
            load_project_metadata,
            scan_repository,
            run_security_agent,
            run_builder_agent,
            run_performance_agent,
            run_qa_agent,
            run_compliance_agent,
            run_documentation_agent,
            verify_findings_with_sandbox,  # Layer 3: Execution verification
            synthesize_findings,
            mark_audit_run_failed,
            # Plan / Build
            generate_project_plan,
            evaluate_build_quality_gates,
            run_build_repo_validation,
            save_build_result,
            save_evolve_result,
            maybe_push_build_report_branch,
            merge_build_git_metadata,
            # Fix pipeline activities
            generate_fix,
            verify_fix,
            persist_fix,
            escalate_to_human,
        ],
    )
    logger.info(
        "Temporal worker registered on queue: %s (5 workflows, 21 activities)",
        settings.temporal_task_queue,
    )

    # ── Run worker with graceful shutdown ─────────────────────────────
    stop_event = asyncio.Event()

    def _handle_signal(sig):
        logger.info("Received signal %s, shutting down...", sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    # Run the worker until we get a signal
    async with worker:
        logger.info("Tron Worker ready. Waiting for tasks...")
        await stop_event.wait()

    # ── Cleanup ───────────────────────────────────────────────────────
    await close_redis()
    await close_db()
    logger.info("Tron Worker stopped.")


if __name__ == "__main__":
    asyncio.run(main())
