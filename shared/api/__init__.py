"""Spine REST API (STORY-9.9.2).

FastAPI surface mounted at ``/api/v2/*`` — thin wrapper over the unified
MCP server (``shared.mcp``) + direct Postgres reads against
``spine_lifecycle`` and ``spine_audit``. Replaces the dev-only
``shared/ui/approvals/proxy.py``. UI is the primary consumer.
"""

from __future__ import annotations

__all__: list[str] = ["create_app"]


def create_app():  # pragma: no cover - thin re-export shim
    """Lazy re-export of :func:`shared.api.app.create_app` for ``uvicorn`` users."""
    from shared.api.app import create_app as _create_app

    return _create_app()
