"""
shared.schemas.federation
=========================

Pydantic v2 wire models for the federation subsystem (#4, #10, #16).

These models are the on-the-wire shape — they sit on the boundary
between `shared/mcp/tools/federation.py` (MCP) and
`shared/api/routes/federation.py` (REST) and the Python dataclasses
inside `federation/`. The dataclasses are the *durable* surface (DB
mirrors); these BaseModels are the *call/response* surface.

Versioning: every schema includes a `_v` integer field so the
federation MCP envelope can route to the right model on upgrades. The
inaugural release is `v1` — anything published in Wave 4.
"""

from __future__ import annotations

from .consent_v1 import (
    ConsentClass,
    ConsentDecisionV1,
    ConsentGrantV1,
    ConsentRevokeV1,
    HubConsentSummaryV1,
    HubRegistrationV1,
    UpdateCascadePushV1,
    UpdateCascadePullV1,
    UpdateRolloutStatus,
)

__all__ = [
    "ConsentClass",
    "ConsentDecisionV1",
    "ConsentGrantV1",
    "ConsentRevokeV1",
    "HubConsentSummaryV1",
    "HubRegistrationV1",
    "UpdateCascadePushV1",
    "UpdateCascadePullV1",
    "UpdateRolloutStatus",
]
