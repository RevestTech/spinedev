"""Live role activity log — SSE + in-process ring buffer for Hub terminal UI."""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("spine.runtime.role_activity")

_MAX_LINES = 800
_RING: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=_MAX_LINES))


def _format_line(*, role: str, message: str) -> str:
    ts = datetime.now(UTC).strftime("%H:%M:%S")
    return f"[{ts}] {role}: {message}"


def role_log(
    project_uuid: str,
    role: str,
    message: str,
    *,
    level: str = "info",
    stream: str = "stdout",
) -> None:
    """Append a terminal line and broadcast on the decisions SSE stream."""
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
    try:
        from shared.api.routes.decisions import publish_event  # noqa: PLC0415

        publish_event(event)
    except Exception as exc:  # noqa: BLE001
        logger.debug("role_log_publish_failed", extra={"error": str(exc)})


def get_terminal_log(project_uuid: str, *, limit: int = 500) -> list[dict[str, Any]]:
    """Recent terminal lines for a project (newest last)."""
    dq = _RING.get(project_uuid)
    if not dq:
        return []
    cap = max(1, min(limit, _MAX_LINES))
    if len(dq) <= cap:
        return list(dq)
    return list(dq)[-cap:]


__all__ = ["get_terminal_log", "role_log"]
