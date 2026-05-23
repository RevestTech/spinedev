"""Tests for master role portfolio briefings."""

from __future__ import annotations

from shared.runtime.master_briefing import (
    PortfolioSnapshot,
    ProjectRow,
    compose_director_briefing,
    push_master_briefings,
)


def test_compose_director_briefing_lists_projects() -> None:
    snap = PortfolioSnapshot(projects=[
        ProjectRow("u1", "Alpha", "plan_in_progress", {"prd_md": "x"}),
        ProjectRow("u2", "Beta", "build_in_progress", {"code_intro_md": "y"}),
    ])
    body = compose_director_briefing("director_product", "Portfolio product status", snap)
    assert "Alpha" in body
    assert "Beta" in body
    assert "Active projects:** 2" in body


def test_push_master_briefings_enqueues_cards() -> None:
    from shared.api.routes.decisions import get_store

    snap = PortfolioSnapshot(projects=[
        ProjectRow("u1", "Alpha", "plan_in_progress", {}),
    ])
    count = push_master_briefings(snap)
    assert count == 4
    pending = get_store().list(status_filter="pending")
    kinds = {c.metadata.get("kind") for c in pending}
    assert "master_daily_briefing" in kinds
