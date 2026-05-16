"""Global LLM spend vs configured budget (enforcement before provider calls)."""

from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import func, select

from tron.api.config import settings
from tron.domain.models import LLMUsage
from tron.infra.db.session import _session_factory

logger = logging.getLogger(__name__)


class LLMBudgetExceeded(RuntimeError):
    """Raised when cumulative LLM spend has reached the hard budget cap."""

    def __init__(self, spent_usd: float, budget_usd: float) -> None:
        self.spent_usd = spent_usd
        self.budget_usd = budget_usd
        super().__init__(
            f"LLM budget exceeded: spent ${spent_usd:.4f} >= cap ${budget_usd:.2f}. "
            "Raise TRON_LLM_BUDGET_USD or set TRON_LLM_BUDGET_ENFORCE=false for dev."
        )


async def get_total_llm_spend_usd() -> float:
    """Sum of all persisted LLM usage (USD)."""
    if _session_factory is None:
        return 0.0
    async with _session_factory() as session:
        total = await session.scalar(
            select(func.coalesce(func.sum(LLMUsage.cost_usd), 0))
        )
    if total is None:
        return 0.0
    return float(Decimal(total))


async def assert_llm_budget_allows_estimated_call() -> None:
    """Block new billable LLM calls when hard cap is reached; warn past soft cap."""
    if not settings.tron_llm_budget_enforce:
        return

    budget = settings.tron_llm_budget_usd
    if budget <= 0:
        return

    spent = await get_total_llm_spend_usd()
    soft = budget * settings.tron_llm_soft_cap_pct

    if spent >= budget:
        raise LLMBudgetExceeded(spent, budget)

    if spent >= soft:
        logger.warning(
            "LLM spend %.4f USD is above soft cap (%.2f%% of $%.2f budget)",
            spent,
            settings.tron_llm_soft_cap_pct * 100,
            budget,
        )
