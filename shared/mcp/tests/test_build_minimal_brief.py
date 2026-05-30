"""Tests for the V3 B4 bounded-retrieval directive wiring in
``shared.mcp.tools.build`` (build_dispatch).

Covers:
  * SYNTHESIZE_MINIMAL_BRIEF + DISPATCH_MINIMAL_BRIEF route to
    ``dispatch_build_bounded`` instead of the fat ``dispatch_build``.
  * The bounded path's response surfaces V3 #30a observation fields
    (``summary``, ``next_actions``) so callers can branch without
    re-parsing ``data``.
  * The fat path is unchanged — SYNTHESIZE_BRIEF still calls
    ``dispatch_build``.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from shared.mcp.tools.build import (
    BuildDispatchInput,
    _MINIMAL_BRIEF_DIRECTIVES,
    build_dispatch,
)


class _FakeResult:
    """Stand-in for build.runtime.build_dispatcher.DispatchResult."""

    def __init__(
        self, *, brief_id: str, goals: int, warnings: list[str] | None = None,
    ) -> None:
        self.brief_id = brief_id
        self.engineering_goals_count = goals
        self.warnings = warnings or []
        self.audit_event_count = 2


# ─── routing ───


@pytest.mark.parametrize(
    "directive", sorted(_MINIMAL_BRIEF_DIRECTIVES),
)
def test_minimal_directive_routes_to_dispatch_build_bounded(
    directive: str,
) -> None:
    fake_fat = _FakeResult(brief_id="brief_fat_xyz", goals=10)
    fake_min = _FakeResult(brief_id="brief_min_xyz", goals=3)
    with patch(
        "build.runtime.build_dispatcher.dispatch_build",
        return_value=fake_fat,
    ) as fat, patch(
        "build.runtime.build_dispatcher.dispatch_build_bounded",
        return_value=fake_min,
    ) as bounded:
        response = build_dispatch(BuildDispatchInput(
            project_id="abcd1234ef560000",
            pipeline_version="1.0.0",
            role="orchestrator",
            directive=directive,
            actor="orchestrator",
        ))

    bounded.assert_called_once()
    fat.assert_not_called()
    assert response.status == "ok"
    assert response.data["brief_id"] == "brief_min_xyz"
    assert response.summary is not None
    assert "minimal brief" in response.summary
    assert response.next_actions
    assert any(
        "minimal_brief" in a or "engineer.read_minimal_brief" in a
        for a in response.next_actions
    )


def test_synthesize_brief_still_routes_to_fat_dispatch() -> None:
    fake_fat = _FakeResult(brief_id="brief_fat_xyz", goals=10)
    fake_min = _FakeResult(brief_id="brief_min_xyz", goals=3)
    with patch(
        "build.runtime.build_dispatcher.dispatch_build",
        return_value=fake_fat,
    ) as fat, patch(
        "build.runtime.build_dispatcher.dispatch_build_bounded",
        return_value=fake_min,
    ) as bounded:
        response = build_dispatch(BuildDispatchInput(
            project_id="abcd1234ef560000",
            pipeline_version="1.0.0",
            role="orchestrator",
            directive="SYNTHESIZE_BRIEF",
            actor="orchestrator",
        ))

    fat.assert_called_once()
    bounded.assert_not_called()
    assert response.status == "ok"
    assert response.data["brief_id"] == "brief_fat_xyz"
    # Fat path next_actions list is shorter (no minimal-brief hint).
    assert response.next_actions == [
        "build_completed when implementer reports back",
    ]
