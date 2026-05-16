"""FastAPI dependencies — DB pool, MCP client, identity stub (STORY-9.9.2).

``get_db_pool`` is a singleton Postgres handle (subprocess ``psql`` for
v1; swap for asyncpg later). ``get_mcp_client`` dispatches into the
in-process MCP tool registry. ``current_user`` is the auth stub —
returns the ``X-Spine-Actor`` header or ``local-user``.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Any

from fastapi import Request

SPINE_DB_URL = os.environ.get("SPINE_DB_URL", "postgresql://spine:spine@localhost:33000/spine")


@dataclass
class DbHandle:
    """Tiny wrapper exposing async ``fetch`` over psql; returns ``[{_row: str}]``."""

    url: str

    async def fetch(self, sql: str) -> list[dict[str, Any]]:
        """Run a SELECT and return one dict per output line."""
        cmd = ["psql", self.url, "-At", "-v", "ON_ERROR_STOP=1", "-c", sql]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if proc.returncode != 0:
            raise RuntimeError(f"psql rc={proc.returncode}: {proc.stderr.strip()}")
        return [{"_row": line} for line in proc.stdout.splitlines() if line]

    async def ping(self) -> bool:
        """Return True when ``SELECT 1`` succeeds."""
        try:
            await self.fetch("SELECT 1;")
            return True
        except Exception:
            return False


_DB: DbHandle | None = None


def get_db_pool() -> DbHandle:
    """Process-wide DB handle (lazy singleton)."""
    global _DB
    if _DB is None:
        _DB = DbHandle(url=SPINE_DB_URL)
    return _DB


class McpClient:
    """In-process dispatcher to the unified MCP tool registry."""

    def call(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate payload, invoke the tool, return its data dict."""
        from shared.mcp.tools import TOOL_REGISTRY, discover_tools

        if not TOOL_REGISTRY:
            discover_tools("shared.mcp.tools")
        spec = TOOL_REGISTRY.get(name)
        if spec is None:
            raise KeyError(f"MCP tool not registered: {name!r}")
        validated = spec.input_model.model_validate(payload)
        response = spec.fn(validated)
        return response.model_dump(mode="json") if hasattr(response, "model_dump") else dict(response)


def get_mcp_client() -> McpClient:
    """FastAPI dependency: in-process MCP client."""
    return McpClient()


def current_user(request: Request) -> str:
    """Auth stub — returns ``X-Spine-Actor`` header or ``local-user``."""
    return (request.headers.get("X-Spine-Actor") or "").strip() or "local-user"
