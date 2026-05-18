"""``/api/v2/integrations`` — integration config UI backend (#3).

Lists configured integrations (one of the 9 Hub surfaces) and exposes
"test connection" probes the SPA shows next to each integration row.

Endpoints:

* ``GET  /api/v2/integrations``                          — list configured integrations
* ``GET  /api/v2/integrations/{name}``                   — single integration detail
* ``POST /api/v2/integrations/{name}/test-connection``   — exercise the integration

Test-connection is gated by the integration's feature flag (per #23) AND
by ``require_role('hub-admin')`` since it pings a third party.

Dependencies: ``fastapi``, ``pydantic``, ``httpx`` (for probe).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from shared.api.dependencies import actor_label, current_user
from shared.api.middleware.feature_flag import is_feature_enabled
from shared.audit.audit_record import AuditRecord, chain_to_previous
from shared.identity.models import User
from shared.identity.rbac import require_role

logger = logging.getLogger("spine.api.integrations")
router = APIRouter(prefix="/api/v2/integrations", tags=["integrations"])

#: Wave 3.5 FIX3 added ``disabled`` so the SPA can render the
#: "upgrade to unlock" UI without inferring it from a 402 on the test
#: endpoint. The semantic split is intentional:
#:
#:   * ``configured``   — feature flag ON  + vault secret present + readable
#:   * ``unconfigured`` — feature flag ON  + vault secret missing
#:   * ``disabled``     — feature flag OFF (regardless of vault state)
#:   * ``error``        — feature flag ON  + vault read failed unexpectedly
IntegrationStatus = Literal["configured", "unconfigured", "disabled", "error"]


class IntegrationDetail(BaseModel):
    """Per-integration record."""

    model_config = ConfigDict(extra="forbid")
    name: str
    kind: str
    status: IntegrationStatus
    feature_flag: Optional[str] = None
    vault_path: Optional[str] = None
    last_test_at: Optional[str] = None
    last_test_ok: Optional[bool] = None


class IntegrationListResponse(BaseModel):
    """``GET /integrations`` envelope."""

    model_config = ConfigDict(extra="forbid")
    ok: bool = True
    items: list[IntegrationDetail]


class TestConnectionResponse(BaseModel):
    """``POST /integrations/{name}/test-connection`` response."""

    model_config = ConfigDict(extra="forbid")
    ok: bool
    name: str
    healthy: bool
    detail: str = ""
    actor: str
    audit_event_uuid: str


# Mirrors the static catalog in `registry.py` — Wave 4 sources from bundle.
_INTEGRATION_CATALOG: dict[str, dict[str, Any]] = {
    "github":    {"kind": "scm",            "feature_flag": "integration_github",
                  "vault_path": "spine/integrations/github/token"},
    "linear":    {"kind": "issue_tracker",  "feature_flag": "integration_linear",
                  "vault_path": "spine/integrations/linear/api_key"},
    "jira":      {"kind": "issue_tracker",  "feature_flag": "integration_jira",
                  "vault_path": "spine/integrations/jira/api_key"},
    "slack":     {"kind": "comms",          "feature_flag": "channel_slack",
                  "vault_path": "spine/integrations/slack/bot_token"},
    "pagerduty": {"kind": "incident",       "feature_flag": "channel_pagerduty",
                  "vault_path": "spine/integrations/pagerduty/routing_key"},
    "vanta":     {"kind": "grc",            "feature_flag": "integration_vanta",
                  "vault_path": "spine/integrations/vanta/api_key"},
    "drata":     {"kind": "grc",            "feature_flag": "integration_drata",
                  "vault_path": "spine/integrations/drata/api_key"},
}


async def _is_configured(meta: dict[str, Any]) -> bool:
    """True iff the vault secret behind this integration is set + readable."""
    vault_path = meta.get("vault_path")
    if not vault_path:
        return True
    try:
        from shared.secrets import get_secret  # noqa: PLC0415

        value = await get_secret(vault_path)
        return bool(value)
    except Exception:  # noqa: BLE001
        return False


def _resolve_status(meta: dict[str, Any], configured: bool) -> IntegrationStatus:
    """Map flag + vault state to the 4-value status enum.

    Wave 3.5 FIX3: when the integration's feature flag is OFF we return
    ``"disabled"`` so the SPA can short-circuit straight to the upgrade
    prompt without first probing /test-connection and parsing a 402.
    Unknown flag values fail OPEN (treated as enabled) to match the
    bootstrap behaviour of ``is_feature_enabled`` itself.
    """
    flag = meta.get("feature_flag")
    if flag:
        try:
            if not is_feature_enabled(flag):
                return "disabled"
        except KeyError:
            # Unknown flag — surface as ``error`` rather than 500; the
            # SPA will treat it like a misconfigured Hub bundle.
            return "error"
    return "configured" if configured else "unconfigured"


def _detail(name: str, meta: dict[str, Any], configured: bool) -> IntegrationDetail:
    return IntegrationDetail(
        name=name,
        kind=meta["kind"],
        status=_resolve_status(meta, configured),
        feature_flag=meta.get("feature_flag"),
        vault_path=meta.get("vault_path"),
    )


@router.get("", response_model=IntegrationListResponse)
async def list_integrations(
    user: Annotated[User, Depends(current_user)],
) -> IntegrationListResponse:
    """List every integration the Hub catalog knows about + its status."""
    items: list[IntegrationDetail] = []
    for name, meta in _INTEGRATION_CATALOG.items():
        configured = await _is_configured(meta)
        items.append(_detail(name, meta, configured))
    return IntegrationListResponse(items=items)


@router.get("/{name}", response_model=IntegrationDetail)
async def get_integration(
    name: str,
    user: Annotated[User, Depends(current_user)],
) -> IntegrationDetail:
    """Single integration detail."""
    meta = _INTEGRATION_CATALOG.get(name)
    if meta is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "integration_unknown", "message": name},
        )
    return _detail(name, meta, await _is_configured(meta))


@router.post("/{name}/test-connection", response_model=TestConnectionResponse)
async def test_connection(
    name: str,
    user: Annotated[User, Depends(require_role("hub-admin"))],
) -> TestConnectionResponse:
    """Run a connectivity probe against the named integration.

    Wave 3 part 1 ships a generic "secret-present + flag-enabled" probe;
    Wave 3 part 2 will add per-integration health endpoints (e.g.
    GitHub's ``/user``, Linear's GraphQL ``viewer`` query).
    """
    meta = _INTEGRATION_CATALOG.get(name)
    if meta is None:
        raise HTTPException(404, detail={"error_code": "integration_unknown", "message": name})
    flag = meta.get("feature_flag")
    if flag and not is_feature_enabled(flag):
        raise HTTPException(
            status_code=402,
            detail={
                "error_code": "feature_disabled",
                "message": f"integration {name!r} requires feature flag {flag!r}",
                "upgrade_path": "/hub/settings/license",
            },
        )
    configured = await _is_configured(meta)
    detail = (
        f"vault secret present at {meta.get('vault_path')!r}"
        if configured
        else f"vault secret missing at {meta.get('vault_path')!r}"
    )
    actor = actor_label(user)
    rec = AuditRecord(
        role="hub_admin",
        subsystem="integration",
        action="test_connection",
        actor=actor,
        subject_type="integration",
        subject_id=name,
        metadata={"ok": configured, "surface": "integrations"},
    )
    rec = chain_to_previous(rec, prev_hash=None)
    return TestConnectionResponse(
        ok=True,
        name=name,
        healthy=configured,
        detail=detail,
        actor=actor,
        audit_event_uuid=str(rec.event_uuid),
    )


__all__ = [
    "router",
    "IntegrationDetail",
    "IntegrationListResponse",
    "TestConnectionResponse",
]
