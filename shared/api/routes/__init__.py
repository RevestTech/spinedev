"""Spine REST route modules (STORY-9.9.2).

Each module owns one ``/api/v2/<resource>`` prefix. ``app.py`` imports
``ALL_ROUTERS`` and mounts each in turn so route registration stays in a
single, ordered list.
"""

from __future__ import annotations

from shared.api.routes.approvals import router as approvals_router
from shared.api.routes.audit import router as audit_router
from shared.api.routes.projects import router as projects_router

ALL_ROUTERS = [projects_router, approvals_router, audit_router]

__all__: list[str] = ["ALL_ROUTERS", "approvals_router", "audit_router", "projects_router"]
