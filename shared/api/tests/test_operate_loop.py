"""Operate-phase autonomous loop — feature complete, promote, next dispatch."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from shared.api.routes import _project_recovery


def test_operate_devops_ack_completes_and_promotes_next() -> None:
    md = {
        "feature_iteration_active": True,
        "code_review_blocked": True,
        "feature_requests": [
            {"status": "completed", "feature": "cart", "priority": 0},
            {"status": "in_progress", "feature": "quiz", "priority": 1},
            {"status": "backlog", "feature": "mix bag", "priority": 2},
        ],
    }
    patch = _project_recovery.operate_devops_ack_metadata_patch(md)
    merged = {**md, **patch}

    assert merged["feature_requests"][1]["status"] == "completed"
    assert merged["feature_requests"][2]["status"] == "requested"
    assert merged["feature_iteration_active"] is False
    assert merged["code_review_blocked"] is False
    assert merged["latest_feature_request"]


def test_operate_devops_ack_without_backlog_clears_iteration() -> None:
    md = {
        "feature_iteration_active": True,
        "feature_requests": [
            {"status": "in_progress", "feature": "only feature", "priority": 1},
        ],
    }
    patch = _project_recovery.operate_devops_ack_metadata_patch(md)
    merged = {**md, **patch}

    assert merged["feature_requests"][0]["status"] == "completed"
    assert merged["feature_iteration_active"] is False
    assert _project_recovery._pending_feature_request(merged) is None


def test_dispatch_next_operate_feature_skips_when_none_queued() -> None:
    result = asyncio.run(
        _project_recovery.dispatch_next_operate_feature(
            "00000000-0000-0000-0000-00000000abcd",
            {"feature_requests": [{"status": "completed", "feature": "x"}]},
        )
    )
    assert result["ok"] is True
    assert result.get("skipped") is True


def test_dispatch_next_operate_feature_starts_retry_feature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatch = AsyncMock(return_value={"ok": True, "action": "retry_feature"})
    monkeypatch.setattr(_project_recovery, "recovery_dispatch", dispatch)

    md = {
        "feature_requests": [
            {"status": "requested", "feature": "next thing", "priority": 2},
        ],
    }
    result = asyncio.run(
        _project_recovery.dispatch_next_operate_feature(
            "00000000-0000-0000-0000-00000000abcd",
            md,
            actor="hub",
        )
    )

    assert result["ok"] is True
    dispatch.assert_awaited_once_with(
        "00000000-0000-0000-0000-00000000abcd",
        "retry_feature",
        actor="hub",
        auto_loop=True,
    )


def test_dispatch_next_operate_feature_respects_inflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatch = AsyncMock()
    monkeypatch.setattr(_project_recovery, "recovery_dispatch", dispatch)

    md = {
        "recovery_dispatch_in_flight": {"action": "retry_engineer"},
        "feature_requests": [{"status": "requested", "feature": "queued"}],
    }
    result = asyncio.run(
        _project_recovery.dispatch_next_operate_feature(
            "00000000-0000-0000-0000-00000000abcd",
            md,
        )
    )

    assert result["ok"] is False
    assert result["error"] == "dispatch_in_flight"
    dispatch.assert_not_awaited()
