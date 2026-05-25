"""Live role activity log — SSE + in-process ring buffer + Postgres durability."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("spine.runtime.role_activity")

_MAX_LINES = 800
_RING: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=_MAX_LINES))

_INSERT_SQL = """
INSERT INTO spine_hub.project_role_log
    (project_uuid, role, message, level, formatted, ts)
VALUES ($1, $2, $3, $4, $5, $6)
"""

_SELECT_RECENT_SQL = """
SELECT role, message, level, formatted, ts
FROM spine_hub.project_role_log
WHERE project_uuid = $1
ORDER BY id DESC
LIMIT $2
"""


def _format_line(*, role: str, message: str) -> str:
    ts = datetime.now(UTC).strftime("%H:%M:%S")
    return f"[{ts}] {role}: {message}"


def _line_dedupe_key(line: dict[str, Any]) -> tuple[float, str]:
    ts = line.get("ts")
    try:
        ts_val = float(ts) if ts is not None else 0.0
    except (TypeError, ValueError):
        ts_val = 0.0
    return (ts_val, str(line.get("message") or ""))


def merge_terminal_lines(
    *sources: list[dict[str, Any]],
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Merge persisted + in-memory lines, dedupe by (ts, message), newest last."""
    seen: set[tuple[float, str]] = set()
    merged: list[dict[str, Any]] = []
    for source in sources:
        for line in source:
            key = _line_dedupe_key(line)
            if key in seen:
                continue
            seen.add(key)
            merged.append(line)
    merged.sort(key=lambda ln: _line_dedupe_key(ln)[0])
    cap = max(1, min(limit, _MAX_LINES))
    if len(merged) <= cap:
        return merged
    return merged[-cap:]


def _row_to_event(row: dict[str, Any], project_uuid: str) -> dict[str, Any]:
    ts_raw = row.get("ts")
    if isinstance(ts_raw, datetime):
        ts_val = ts_raw.timestamp()
    else:
        ts_val = time.time()
    return {
        "type": "role_log",
        "project_uuid": project_uuid,
        "role": row.get("role") or "",
        "message": row.get("message") or "",
        "level": row.get("level") or "info",
        "stream": "stdout",
        "ts": ts_val,
        "formatted": row.get("formatted") or "",
    }


async def _persist_role_log(event: dict[str, Any]) -> None:
    from shared.api.dependencies import DbPoolNotInitialized, get_db_pool_raw  # noqa: PLC0415

    try:
        pool = get_db_pool_raw()
    except DbPoolNotInitialized:
        return

    ts_raw = event.get("ts")
    if isinstance(ts_raw, (int, float)):
        ts_dt = datetime.fromtimestamp(float(ts_raw), UTC)
    elif isinstance(ts_raw, datetime):
        ts_dt = ts_raw if ts_raw.tzinfo else ts_raw.replace(tzinfo=UTC)
    else:
        ts_dt = datetime.now(UTC)

    try:
        async with pool.acquire() as conn:
            await conn.execute(
                _INSERT_SQL,
                event["project_uuid"],
                event.get("role"),
                event["message"],
                event.get("level") or "info",
                event.get("formatted"),
                ts_dt,
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("role_log_persist_failed", extra={"error": str(exc)})


def _schedule_persist(event: dict[str, Any]) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_persist_role_log(event))


async def _fetch_persisted_lines(
    project_uuid: str,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    from shared.api.dependencies import DbPoolNotInitialized, get_db_pool_raw  # noqa: PLC0415

    try:
        pool = get_db_pool_raw()
    except DbPoolNotInitialized:
        return []

    cap = max(1, min(limit, _MAX_LINES))
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(_SELECT_RECENT_SQL, project_uuid, cap)
    except Exception as exc:  # noqa: BLE001
        logger.debug("role_log_fetch_failed", extra={"error": str(exc)})
        return []

    events = [_row_to_event(dict(row), project_uuid) for row in reversed(rows)]
    return events


def role_log(
    project_uuid: str,
    role: str,
    message: str,
    *,
    level: str = "info",
    stream: str = "stdout",
) -> None:
    """Append a terminal line, persist to Postgres, and broadcast on SSE."""
    text = (message or "").strip()
    if not text:
        return
    event: dict[str, Any] = {
        "type": "role_log",
        "project_uuid": project_uuid,
        "role": role,
        "message": text,
        "level": level,
        "stream": stream,
        "ts": time.time(),
        "formatted": _format_line(role=role, message=text),
    }
    _RING[project_uuid].append(event)
    _schedule_persist(event)
    try:
        from shared.api.routes.decisions import publish_event  # noqa: PLC0415

        publish_event(event)
    except Exception as exc:  # noqa: BLE001
        logger.debug("role_log_publish_failed", extra={"error": str(exc)})


async def get_terminal_log(project_uuid: str, *, limit: int = 500) -> list[dict[str, Any]]:
    """Recent terminal lines for a project (newest last), DB + ring buffer."""
    ring_lines = list(_RING.get(project_uuid) or ())
    persisted = await _fetch_persisted_lines(project_uuid, limit=limit)
    return merge_terminal_lines(persisted, ring_lines, limit=limit)


__all__ = ["get_terminal_log", "merge_terminal_lines", "role_log"]
