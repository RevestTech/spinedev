"""Tests for live role activity terminal log."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from shared.runtime.role_activity import (
    get_terminal_log,
    merge_terminal_lines,
    role_log,
)


def test_role_log_ring_buffer() -> None:
    pid = "00000000-0000-0000-0000-00000000test"
    role_log(pid, "engineer", "first line")
    role_log(pid, "engineer", "second line")
    lines = asyncio.run(get_terminal_log(pid))
    assert len(lines) == 2
    assert lines[0]["message"] == "first line"
    assert lines[1]["type"] == "role_log"
    assert "engineer:" in lines[1]["formatted"]


def test_merge_terminal_lines_dedupes_by_ts_and_message() -> None:
    persisted = [
        {
            "type": "role_log",
            "project_uuid": "p1",
            "role": "engineer",
            "message": "alpha",
            "level": "info",
            "stream": "stdout",
            "ts": 100.0,
            "formatted": "[00:00:00] engineer: alpha",
        },
        {
            "type": "role_log",
            "project_uuid": "p1",
            "role": "engineer",
            "message": "beta",
            "level": "info",
            "stream": "stdout",
            "ts": 101.0,
            "formatted": "[00:00:01] engineer: beta",
        },
    ]
    ring = [
        {
            "type": "role_log",
            "project_uuid": "p1",
            "role": "engineer",
            "message": "beta",
            "level": "info",
            "stream": "stdout",
            "ts": 101.0,
            "formatted": "[00:00:01] engineer: beta",
        },
        {
            "type": "role_log",
            "project_uuid": "p1",
            "role": "engineer",
            "message": "gamma",
            "level": "info",
            "stream": "stdout",
            "ts": 102.0,
            "formatted": "[00:00:02] engineer: gamma",
        },
    ]
    merged = merge_terminal_lines(persisted, ring, limit=10)
    assert [line["message"] for line in merged] == ["alpha", "beta", "gamma"]


def test_get_terminal_log_merges_db_and_ring(monkeypatch) -> None:
    pid = "00000000-0000-0000-0000-00000000db01"
    ring_only = {
        "type": "role_log",
        "project_uuid": pid,
        "role": "engineer",
        "message": "live tail",
        "level": "info",
        "stream": "stdout",
        "ts": 200.0,
        "formatted": "[00:00:00] engineer: live tail",
    }
    role_log(pid, ring_only["role"], ring_only["message"])
    # Overwrite ring entry ts so merge test is deterministic.
    from shared.runtime import role_activity as mod

    mod._RING[pid][-1]["ts"] = ring_only["ts"]

    async def fake_fetch(project_uuid: str, *, limit: int) -> list[dict]:
        assert project_uuid == pid
        assert limit == 500
        return [
            {
                "type": "role_log",
                "project_uuid": pid,
                "role": "engineer",
                "message": "from db",
                "level": "info",
                "stream": "stdout",
                "ts": 100.0,
                "formatted": "[00:00:00] engineer: from db",
            }
        ]

    monkeypatch.setattr(mod, "_fetch_persisted_lines", fake_fetch)

    lines = asyncio.run(get_terminal_log(pid))
    assert [line["message"] for line in lines] == ["from db", "live tail"]


def test_row_to_event_converts_db_timestamp() -> None:
    from shared.runtime.role_activity import _row_to_event

    ts = datetime(2026, 5, 24, 12, 0, 0, tzinfo=UTC)
    event = _row_to_event(
        {
            "role": "engineer",
            "message": "hello",
            "level": "info",
            "formatted": "[12:00:00] engineer: hello",
            "ts": ts,
        },
        "proj-uuid",
    )
    assert event["message"] == "hello"
    assert event["ts"] == ts.timestamp()


def test_persist_role_log_uses_pool(monkeypatch) -> None:
    from shared.runtime import role_activity as mod

    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="INSERT 1")

    class _AcquireCtx:
        async def __aenter__(self):  # noqa: ANN204
            return conn

        async def __aexit__(self, *args):  # noqa: ANN002, ANN204
            return False

    pool = AsyncMock()
    pool.acquire = lambda: _AcquireCtx()

    monkeypatch.setattr(
        "shared.api.dependencies.get_db_pool_raw",
        lambda: pool,
    )

    event = {
        "project_uuid": "00000000-0000-0000-0000-00000000persist",
        "role": "engineer",
        "message": "persist me",
        "level": "info",
        "formatted": "[00:00:00] engineer: persist me",
        "ts": 123.456,
    }
    asyncio.run(mod._persist_role_log(event))
    conn.execute.assert_awaited_once()
