"""Async-local context for attributing LLM calls to a project/workflow (usage ledger)."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Iterator, Optional
from uuid import UUID

from temporalio import activity

_var: ContextVar[Optional["LLMUsageRecordContext"]] = ContextVar(
    "llm_usage_record_ctx", default=None
)


@dataclass(frozen=True)
class LLMUsageRecordContext:
    project_id: UUID
    workflow_id: Optional[str] = None
    workflow_run_id: Optional[str] = None
    operation_mode: Optional[str] = None
    operation_detail: Optional[str] = None


def get_llm_usage_context() -> Optional[LLMUsageRecordContext]:
    return _var.get()


@contextmanager
def llm_usage_scope(ctx: LLMUsageRecordContext) -> Iterator[None]:
    tok: Token = _var.set(ctx)
    try:
        yield
    finally:
        _var.reset(tok)


def get_activity_workflow_ids() -> tuple[Optional[str], Optional[str]]:
    """Return (workflow_id, workflow_run_id) when inside a Temporal activity."""
    try:
        info = activity.info()
    except Exception:
        return None, None
    wf = getattr(info, "workflow_id", None)
    run = getattr(info, "workflow_run_id", None) or getattr(info, "run_id", None)
    return (
        str(wf) if wf else None,
        str(run) if run else None,
    )
