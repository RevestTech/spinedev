"""Pending decision counts must not double-count one card with uuid + numeric id."""

from __future__ import annotations

import asyncio

import pytest

from shared.api.routes._project_recovery import pending_count_for_project
from shared.api.routes.decisions import DecisionCard, enqueue_decision, get_store


@pytest.fixture(autouse=True)
def _clear_store() -> None:
    """Isolate in-memory decision store between tests."""
    store = get_store()
    if hasattr(store, "_cache"):
        store._cache.clear()  # noqa: SLF001


def test_pending_count_dedupes_uuid_and_numeric_id() -> None:
    enqueue_decision(
        DecisionCard(
            decision_id="card-both",
            decision_class="approval",
            project_id="7",
            title="Approve code",
            metadata={"project_uuid": "uuid-abc"},
        )
    )
    index = asyncio.run(
        __import__(
            "shared.api.routes._project_recovery", fromlist=["_build_pending_decision_index"]
        )._build_pending_decision_index()
    )
    project = {"id": 7, "project_uuid": "uuid-abc"}
    assert pending_count_for_project(project, index) == 1
