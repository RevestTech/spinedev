"""Persist LLM usage rows for cost dashboards."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional
from uuid import UUID

from tron.domain.models import LLMUsage
from tron.infra.db.session import _session_factory

logger = logging.getLogger(__name__)


async def persist_llm_usage(
    *,
    project_id: UUID,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
    duration_ms: int,
    cached: bool,
    cache_key: Optional[str],
    workflow_id: Optional[str],
    workflow_run_id: Optional[str],
    operation_mode: Optional[str],
    operation_detail: Optional[str],
    temperature: Optional[float],
    max_tokens: Optional[int],
) -> None:
    if _session_factory is None:
        logger.debug("persist_llm_usage skipped: DB not initialized")
        return
    row = LLMUsage(
        project_id=project_id,
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
        operation_mode=operation_mode,
        operation_detail=(operation_detail[:255] if operation_detail else None),
        provider=provider,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=Decimal(str(round(cost_usd, 6))),
        duration_ms=duration_ms,
        cached=cached,
        cache_key=cache_key,
        temperature=Decimal(str(round(temperature, 2))) if temperature is not None else None,
        max_tokens=max_tokens,
    )
    try:
        async with _session_factory() as session:
            session.add(row)
            await session.commit()
    except Exception:
        logger.warning("persist_llm_usage failed", exc_info=True)
