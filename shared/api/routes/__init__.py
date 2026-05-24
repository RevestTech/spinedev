"""Spine REST route modules (STORY-9.9.2 + V3 Wave 3 Squad C extensions).

Each module owns one ``/api/v2/<resource>`` prefix. ``app.py`` imports
``ALL_ROUTERS`` and mounts each in turn so route registration stays in a
single, ordered list.

Wave 3 part 1 added 7 Hub-specific surfaces (per #3 enumerated Hub surfaces):
``decisions``, ``role_chat``, ``registry``, ``vault_config``,
``integrations``, ``federation``, ``license``.
"""

from __future__ import annotations

from shared.api.routes.approvals import router as approvals_router
from shared.api.routes.audit import router as audit_router
from shared.api.routes.decisions import router as decisions_router
from shared.api.routes.federation import router as federation_router
from shared.api.routes.hub_inbox import router as hub_inbox_router
from shared.api.routes.intake import router as intake_router
from shared.api.routes.integrations import router as integrations_router
from shared.api.routes.kg import router as kg_router
from shared.api.routes.license import router as license_router
from shared.api.routes.mobile import router as mobile_router
from shared.api.routes.projects import router as projects_router
from shared.api.routes.registry import router as registry_router
from shared.api.routes.role_chat import router as role_chat_router
from shared.api.routes.vault_config import router as vault_config_router
from shared.api.routes.voice import router as voice_router

ALL_ROUTERS = [
    # v2 routes
    projects_router,
    approvals_router,
    audit_router,
    # Wave 3 part 1 (Hub-as-product surfaces)
    decisions_router,
    hub_inbox_router,
    role_chat_router,
    registry_router,
    vault_config_router,
    integrations_router,
    federation_router,
    license_router,
    # Wave 3 part 2 — KG REST front-end (Squad SPA3, drift audit fix)
    kg_router,
    # Wave 6 — mobile + voice scaffolds (#28, #29)
    mobile_router,
    voice_router,
    # Conversational intake — real LLM-backed product role
    intake_router,
]

__all__: list[str] = [
    "ALL_ROUTERS",
    "approvals_router",
    "audit_router",
    "projects_router",
    "decisions_router",
    "hub_inbox_router",
    "role_chat_router",
    "registry_router",
    "vault_config_router",
    "integrations_router",
    "federation_router",
    "kg_router",
    "license_router",
    "mobile_router",
    "voice_router",
]
