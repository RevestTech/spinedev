"""Classify decision cards as project-scoped vs Hub inbox (portfolio messages)."""

from __future__ import annotations

from typing import TYPE_CHECKING

HUB_INBOX_KINDS = frozenset({"master_daily_briefing"})

if TYPE_CHECKING:
    from shared.api.routes.decisions import DecisionCard


def is_hub_inbox_card(card: DecisionCard) -> bool:
    """Master briefings and other portfolio-level inbox items."""
    meta = card.metadata or {}
    if meta.get("kind") in HUB_INBOX_KINDS:
        return True
    if card.decision_class == "briefing" and not card.project_id and not meta.get("project_uuid"):
        return True
    return False


def is_project_decision_card(card: DecisionCard) -> bool:
    return not is_hub_inbox_card(card)


__all__ = ["HUB_INBOX_KINDS", "is_hub_inbox_card", "is_project_decision_card"]
