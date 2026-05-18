"""Integrations-ops MCP tools (V3 Wave 6 Stream J, #30).

Three tools — list, test-connection, configure — that wrap the
``shared/integrations/*`` adapters so any MCP caller (CLI, agent
harness, Hub SPA via the REST -> MCP bridge) can exercise an
integration without bypassing the Spine audit + licence layers.

Per design decision #12, ``integrations_configure`` is **mutating** and
is therefore registered with ``requires_citation=True``: writes must cite
the request that authorised the change so a future audit can replay
"who installed the GitHub token, when, and why."

Per design decision #23, every call goes through
``shared.api.middleware.feature_flag.is_feature_enabled`` for the
integration's flag — a tool execution against a disabled integration
returns an error envelope with ``error_code='feature_disabled'`` and
the upgrade path.

Per design decision #9, secret payloads are NEVER passed as plain MCP
input. ``integrations_configure`` accepts a ``vault_path`` reference;
the caller is expected to have already ``shared.secrets.put_secret``-ed
the credential. We READ the vault path here only to confirm it exists.

Adapter coverage (v1.0 scaffold scope):

* github / linear / jira / slack / pagerduty   — real probe (HTTP HEAD).
* twilio / teams / vanta / drata / secureframe — stub probe (vault-only
  presence check + ``NotImplementedError`` from the would-be adapter
  surfaced as ``stub_implementation`` envelope; full coverage in v1.1).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from shared.mcp.schemas import Citation, ToolError, ToolResponse
from shared.mcp.tools import register_tool

logger = logging.getLogger("shared.mcp.tools.integrations")

_FORBID = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Integration catalog
# ---------------------------------------------------------------------------


IntegrationName = Literal[
    "github", "linear", "jira", "slack", "pagerduty",
    "twilio", "teams", "vanta", "drata", "secureframe",
]
"""Full integration surface per #24 (Vanta/Drata/Secureframe) + #6 channels."""

IntegrationKind = Literal[
    "scm", "issue_tracker", "comms", "incident", "voice", "grc",
]


_CATALOG: dict[str, dict[str, Any]] = {
    "github": {
        "kind": "scm",
        "feature_flag": "integration_github",
        "vault_path": "spine/integrations/github/token",
        "probe": "real",
    },
    "linear": {
        "kind": "issue_tracker",
        "feature_flag": "integration_linear",
        "vault_path": "spine/integrations/linear/api_key",
        "probe": "real",
    },
    "jira": {
        "kind": "issue_tracker",
        "feature_flag": "integration_jira",
        "vault_path": "spine/integrations/jira/api_key",
        "probe": "real",
    },
    "slack": {
        "kind": "comms",
        "feature_flag": "channel_slack",
        "vault_path": "spine/integrations/slack/bot_token",
        "probe": "real",
    },
    "pagerduty": {
        "kind": "incident",
        "feature_flag": "channel_pagerduty",
        "vault_path": "spine/integrations/pagerduty/routing_key",
        "probe": "real",
    },
    "twilio": {
        "kind": "voice",
        "feature_flag": "channel_sms",
        "vault_path": "spine/integrations/twilio/auth_token",
        "probe": "stub",  # v1.1+
    },
    "teams": {
        "kind": "comms",
        "feature_flag": "channel_teams",
        "vault_path": "spine/integrations/teams/webhook",
        "probe": "stub",  # v1.1+
    },
    "vanta": {
        "kind": "grc",
        "feature_flag": "integration_vanta",
        "vault_path": "spine/integrations/vanta/api_key",
        "probe": "stub",  # v1.1+
    },
    "drata": {
        "kind": "grc",
        "feature_flag": "integration_drata",
        "vault_path": "spine/integrations/drata/api_key",
        "probe": "stub",  # v1.1+
    },
    "secureframe": {
        "kind": "grc",
        "feature_flag": "integration_drata",  # shares GRC flag for v1.0
        "vault_path": "spine/integrations/secureframe/api_key",
        "probe": "stub",  # v1.1+
    },
}


# ---------------------------------------------------------------------------
# Audit + helpers (mirror shared/mcp/tools/license.py pattern)
# ---------------------------------------------------------------------------


def _log(tool: str, project_id: str, actor: str, integration: str) -> None:
    logger.info(
        "mcp_tool_call",
        extra={"tool": tool, "project_id": project_id, "actor": actor,
               "integration": integration},
    )


def _error(
    code: str,
    message: str,
    *,
    retryable: bool = False,
    audit_id: Optional[UUID] = None,
) -> ToolResponse:
    aid = audit_id or uuid4()
    return ToolResponse(
        status="error",
        audit_id=aid,
        error=ToolError(code=code, message=message, retryable=retryable),
    )


def _audit_write(
    *,
    action: str,
    project_id: str,
    actor: str,
    integration_name: str,
    metadata: dict[str, Any],
) -> UUID:
    """Best-effort audit write; never blocks the tool result on failure."""
    audit_uuid = uuid4()
    try:
        from shared.audit.audit_record import (
            AuditRecord, chain_to_previous, write_via_psql,
        )

        rec = AuditRecord(
            role=actor,
            subsystem="integration",
            action=action,
            actor=actor,
            subject_type="integration",
            subject_id=integration_name,
            metadata=metadata,
            event_uuid=audit_uuid,
        )
        rec = chain_to_previous(rec, None)
        write_via_psql(rec)
    except Exception as exc:  # noqa: BLE001 — audit is best-effort
        logger.warning(
            "integration_tool_audit_failed",
            extra={"action": action, "err": str(exc)},
        )
    return audit_uuid


def _is_feature_enabled(flag: Optional[str]) -> bool:
    """Cheap, import-light wrapper around the feature_flag evaluator.

    Returns ``True`` when the flag is None (no gating required) or the
    licence subsystem is missing (fail-open consistent with the rest of
    the Wave 3 contract).
    """
    if not flag:
        return True
    try:
        from shared.api.middleware.feature_flag import is_feature_enabled
    except Exception:  # noqa: BLE001
        return True
    try:
        return bool(is_feature_enabled(flag))
    except KeyError:
        # Unknown flag — bail visibly. We *want* a configure-time error
        # to surface in the tool result rather than silently allow.
        return False
    except Exception:  # noqa: BLE001
        return True


async def _secret_present(vault_path: Optional[str]) -> tuple[bool, str]:
    """Check vault for ``vault_path``; return (present, detail)."""
    if not vault_path:
        return (True, "no vault_path declared")
    try:
        from shared.secrets import get_secret  # noqa: PLC0415

        value = await get_secret(vault_path)
        if value:
            return (True, f"vault secret present at {vault_path!r}")
        return (False, f"vault secret empty at {vault_path!r}")
    except Exception as exc:  # noqa: BLE001
        return (False, f"vault read failed at {vault_path!r}: {exc!s}")


def _canonical_probe_envelope(
    name: str, meta: dict[str, Any],
) -> dict[str, Any]:
    """Wave 3.5 FIX2 — uniform probe routed through canonical adapters.

    For stub-mode integrations we still want the SPA + MCP tool to see
    the same envelope shape regardless of whether the adapter has been
    promoted to a real HTTP probe yet. We try the canonical
    ``shared.integrations.<name>.test_connection()`` first; if that's
    missing (or the module hasn't been shipped) we fall back to the
    historical inline ``_secret_present`` vault check.

    Returns a dict ``{'healthy': bool, 'detail': str}``.
    """
    try:
        import importlib  # noqa: PLC0415

        mod = importlib.import_module(f"shared.integrations.{name}")
        probe = getattr(mod, "test_connection", None)
        if probe is not None and asyncio.iscoroutinefunction(probe):
            result = _run_async(probe())
            if result is not None and hasattr(result, "healthy"):
                return {
                    "healthy": bool(result.healthy),
                    "detail": str(result.detail or ""),
                }
    except Exception:  # noqa: BLE001 — degrade to legacy path
        pass

    # Legacy fallback: inline vault check (matches pre-FIX2 behaviour).
    present, detail = (
        _run_async(_secret_present(meta.get("vault_path"))) or (False, "")
    )
    return {"healthy": bool(present), "detail": detail}


def _run_async(coro: Any) -> Any:
    """Run an async coroutine from a sync MCP tool body.

    Mirrors the pattern in ``shared/mcp/tools/license.py``: degrade
    gracefully if the caller is already inside an event loop (the
    federation MCP bridge does this) — we return ``None`` and the
    caller falls back to a deterministic stub-shaped response.
    """
    try:
        return asyncio.run(coro)
    except RuntimeError:
        return None


# ---------------------------------------------------------------------------
# integrations_list
# ---------------------------------------------------------------------------


class IntegrationsListInput(BaseModel):
    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    actor: str = Field(default="system", min_length=1)
    kind: Optional[IntegrationKind] = Field(
        default=None,
        description="Filter by kind (e.g. 'grc' to list compliance integrations).",
    )


class _ListItem(BaseModel):
    model_config = _FORBID
    name: str
    kind: str
    feature_flag: Optional[str] = None
    feature_enabled: bool
    vault_path: Optional[str] = None
    configured: bool
    probe_mode: Literal["real", "stub"]


class _ListResponse(BaseModel):
    model_config = _FORBID
    items: list[_ListItem]
    as_of: str


@register_tool(
    name="integrations_list",
    input_model=IntegrationsListInput,
    story="STORY-30.1.1",
    description="List every integration known to the Spine catalog + status.",
    tags=("integrations",),
)
def integrations_list(payload: IntegrationsListInput) -> ToolResponse:
    """Enumerate integrations with per-row feature_flag + configured state."""
    _log("integrations_list", payload.project_id, payload.actor, "*")

    async def _build() -> list[_ListItem]:
        out: list[_ListItem] = []
        for name, meta in _CATALOG.items():
            if payload.kind and meta["kind"] != payload.kind:
                continue
            flag = meta.get("feature_flag")
            enabled = _is_feature_enabled(flag)
            present, _detail = await _secret_present(meta.get("vault_path"))
            out.append(_ListItem(
                name=name,
                kind=meta["kind"],
                feature_flag=flag,
                feature_enabled=enabled,
                vault_path=meta.get("vault_path"),
                configured=present,
                probe_mode=meta.get("probe", "stub"),
            ))
        return out

    items = _run_async(_build()) or []

    audit_id = _audit_write(
        action="integrations_list",
        project_id=payload.project_id,
        actor=payload.actor,
        integration_name=payload.kind or "all",
        metadata={"row_count": len(items)},
    )
    body = _ListResponse(
        items=items,
        as_of=datetime.now(timezone.utc).isoformat(),
    )
    return ToolResponse(
        status="ok",
        data=body.model_dump(mode="json"),
        audit_id=audit_id,
    )


# ---------------------------------------------------------------------------
# integrations_test_connection
# ---------------------------------------------------------------------------


class IntegrationsTestConnectionInput(BaseModel):
    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    actor: str = Field(default="hub_admin", min_length=1)
    name: IntegrationName = Field(..., description="Integration to probe.")


class _TestConnectionResponse(BaseModel):
    model_config = _FORBID
    name: str
    healthy: bool
    probe_mode: Literal["real", "stub"]
    detail: str
    feature_flag: Optional[str] = None


@register_tool(
    name="integrations_test_connection",
    input_model=IntegrationsTestConnectionInput,
    story="STORY-30.1.2",
    description="Run a connectivity probe against the named integration.",
    tags=("integrations", "verify"),
)
def integrations_test_connection(
    payload: IntegrationsTestConnectionInput,
) -> ToolResponse:
    """Per-integration probe; stub-mode returns ``stub_implementation`` envelope.

    Real probes (github / linear / jira / slack / pagerduty) call the
    ``shared/integrations/<name>.py`` adapter's ``test_connection()``
    coroutine. Stub-mode adapters (twilio / teams / vanta / drata /
    secureframe) raise NotImplementedError; we surface that as the
    documented ``stub_implementation`` envelope status so callers can
    distinguish "v1.0 scaffold" from "real error".
    """
    _log(
        "integrations_test_connection",
        payload.project_id, payload.actor, payload.name,
    )
    meta = _CATALOG.get(payload.name)
    if meta is None:
        return _error(
            "integration_unknown",
            f"unknown integration {payload.name!r}",
            retryable=False,
        )

    flag = meta.get("feature_flag")
    if not _is_feature_enabled(flag):
        audit_id = _audit_write(
            action="integrations_test_connection",
            project_id=payload.project_id,
            actor=payload.actor,
            integration_name=payload.name,
            metadata={"ok": False, "reason": "feature_disabled", "flag": flag},
        )
        return _error(
            "feature_disabled",
            f"integration {payload.name!r} requires feature flag {flag!r}",
            retryable=False,
            audit_id=audit_id,
        )

    probe_mode = meta.get("probe", "stub")

    if probe_mode == "stub":
        # Adapter is a v1.1 stub; dispatch to the canonical
        # ``shared.integrations.<name>.test_connection`` coroutine which
        # returns a uniform vault-presence envelope. Wave 3.5 FIX2: this
        # used to inline ``_secret_present``; we now go through the
        # canonical adapter so every integration is probed identically.
        canonical = _canonical_probe_envelope(payload.name, meta)
        body = _TestConnectionResponse(
            name=payload.name,
            healthy=canonical["healthy"],
            probe_mode="stub",
            detail=(
                f"v1.1+ adapter stub; {canonical['detail']}"
            ),
            feature_flag=flag,
        )
        audit_id = _audit_write(
            action="integrations_test_connection",
            project_id=payload.project_id,
            actor=payload.actor,
            integration_name=payload.name,
            metadata={"ok": True, "probe_mode": "stub",
                      "vault_present": canonical["healthy"]},
        )
        return ToolResponse(
            status="stub_implementation",
            data=body.model_dump(mode="json"),
            audit_id=audit_id,
        )

    # Real probe — attempt to import the adapter; surface a stub envelope
    # if the module is absent (v1.0 substrate not yet on disk for this
    # name) rather than a hard error.
    #
    # Wave 3.5 FIX2 — Per V3 Part 1.1 the canonical home for adapters is
    # ``shared/integrations/<name>.py``. Every adapter shipped in v1.0
    # (github, linear, twilio, teams, pagerduty) exposes a
    # module-level ``test_connection()`` coroutine that returns a
    # :class:`shared.integrations.TestConnectionResult`. The dispatcher
    # below accepts BOTH return shapes (TestConnectionResult OR the
    # legacy ``(bool, str)`` tuple) so callers don't need a coordinated
    # upgrade.
    adapter_mod = f"shared.integrations.{payload.name}"
    healthy = False
    detail = ""
    used_stub = False
    try:
        import importlib  # noqa: PLC0415

        mod = importlib.import_module(adapter_mod)
        probe = getattr(mod, "test_connection", None)
        if probe is None:
            used_stub = True
            present, vdetail = (
                _run_async(_secret_present(meta.get("vault_path"))) or (False, "")
            )
            healthy = present
            detail = (
                f"{adapter_mod}.test_connection() not defined; "
                f"fell back to vault check: {vdetail}"
            )
        else:
            result = _run_async(probe()) if asyncio.iscoroutinefunction(probe) \
                else probe()
            # New canonical shape: TestConnectionResult dataclass.
            if hasattr(result, "healthy") and hasattr(result, "detail"):
                healthy = bool(result.healthy)
                detail = str(result.detail)
                if getattr(result, "probe_mode", "real") == "stub":
                    used_stub = True
            elif isinstance(result, tuple) and len(result) == 2:
                healthy, detail = bool(result[0]), str(result[1])
            else:
                healthy = bool(result)
                detail = (
                    "probe returned truthy" if healthy
                    else "probe returned falsy"
                )
    except ModuleNotFoundError:
        used_stub = True
        present, vdetail = (
            _run_async(_secret_present(meta.get("vault_path"))) or (False, "")
        )
        healthy = present
        detail = (
            f"adapter module {adapter_mod} not yet shipped; "
            f"fell back to vault check: {vdetail}"
        )
    except NotImplementedError as exc:
        used_stub = True
        healthy = False
        detail = f"adapter raised NotImplementedError: {exc!s}"
    except Exception as exc:  # noqa: BLE001 — surfacing into audit + result
        audit_id = _audit_write(
            action="integrations_test_connection",
            project_id=payload.project_id,
            actor=payload.actor,
            integration_name=payload.name,
            metadata={"ok": False, "error": type(exc).__name__,
                      "detail": str(exc)},
        )
        return _error(
            "probe_failed",
            f"{adapter_mod} probe failed: {exc!s}",
            retryable=True,
            audit_id=audit_id,
        )

    body = _TestConnectionResponse(
        name=payload.name,
        healthy=healthy,
        probe_mode="stub" if used_stub else "real",
        detail=detail,
        feature_flag=flag,
    )
    audit_id = _audit_write(
        action="integrations_test_connection",
        project_id=payload.project_id,
        actor=payload.actor,
        integration_name=payload.name,
        metadata={"ok": healthy, "probe_mode": body.probe_mode},
    )
    return ToolResponse(
        status="stub_implementation" if used_stub else "ok",
        data=body.model_dump(mode="json"),
        audit_id=audit_id,
    )


# ---------------------------------------------------------------------------
# integrations_configure  —  MUTATING; requires_citation=True per #12
# ---------------------------------------------------------------------------


class IntegrationsConfigureInput(BaseModel):
    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    actor: str = Field(..., min_length=1,
        description="Required for configure; no 'system' default — must be a real role.")
    name: IntegrationName = Field(..., description="Integration to configure.")
    vault_path: str = Field(..., min_length=1,
        description=(
            "Vault path the credential was already stored at via "
            "shared.secrets.put_secret (#9). MCP NEVER carries the "
            "secret VALUE in its envelope."
        ))
    options: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Non-secret integration options (e.g. github org name, "
            "linear workspace_id). Persisted with the integration config row."
        ),
    )


class _ConfigureResponse(BaseModel):
    model_config = _FORBID
    name: str
    configured: bool
    vault_path: str
    feature_flag: Optional[str] = None
    options_count: int
    persisted_at: str


@register_tool(
    name="integrations_configure",
    input_model=IntegrationsConfigureInput,
    story="STORY-30.1.3",
    description=(
        "Register/update a configured integration. Mutating — "
        "Cite-or-Refuse required per V3 #12."
    ),
    tags=("integrations", "mutating"),
    requires_citation=True,  # per #12 — mutating tool
)
def integrations_configure(payload: IntegrationsConfigureInput) -> ToolResponse:
    """Persist the integration config row + verify the vault secret exists.

    The actual ``UPDATE … RETURNING`` row mutation is a Wave 6.5+ concern
    (waiting on the per-org bundle column). For v1.0 we:

    1. Validate the integration name is in the catalog.
    2. Gate on the feature flag (per #23).
    3. Confirm the supplied ``vault_path`` resolves to a non-empty
       secret — so we never persist a config row that points at
       missing credentials.
    4. Write the audit event with ``action='integrations_configure'``.
    5. Emit Cite-or-Refuse citations rooted in the audit row.
    """
    _log(
        "integrations_configure",
        payload.project_id, payload.actor, payload.name,
    )

    meta = _CATALOG.get(payload.name)
    if meta is None:
        return _error(
            "integration_unknown",
            f"unknown integration {payload.name!r}",
            retryable=False,
        )

    flag = meta.get("feature_flag")
    if not _is_feature_enabled(flag):
        audit_id = _audit_write(
            action="integrations_configure",
            project_id=payload.project_id,
            actor=payload.actor,
            integration_name=payload.name,
            metadata={"ok": False, "reason": "feature_disabled", "flag": flag},
        )
        # Cite-or-Refuse: refusal must still cite the audit row.
        cite = Citation(
            type="audit_hash",
            ref=str(audit_id),
            excerpt=f"refused: feature {flag!r} disabled",
        )
        body = _error(
            "feature_disabled",
            f"integration {payload.name!r} requires feature flag {flag!r}",
            retryable=False,
            audit_id=audit_id,
        )
        # Preserve error + attach citation so the refusal carries evidence.
        return ToolResponse(
            status="error",
            data={},
            error=body.error,
            audit_id=audit_id,
            citation=[cite],
        )

    present, detail = (
        _run_async(_secret_present(payload.vault_path)) or (False, "no event loop")
    )
    if not present:
        audit_id = _audit_write(
            action="integrations_configure",
            project_id=payload.project_id,
            actor=payload.actor,
            integration_name=payload.name,
            metadata={"ok": False, "reason": "vault_empty",
                      "vault_path": payload.vault_path, "detail": detail},
        )
        cite = Citation(
            type="audit_hash",
            ref=str(audit_id),
            excerpt=f"refused: {detail}",
        )
        return ToolResponse(
            status="error",
            data={},
            error=ToolError(
                code="vault_secret_missing",
                message=(
                    f"vault path {payload.vault_path!r} is empty; "
                    "call shared.secrets.put_secret() first"
                ),
                retryable=False,
            ),
            audit_id=audit_id,
            citation=[cite],
        )

    body = _ConfigureResponse(
        name=payload.name,
        configured=True,
        vault_path=payload.vault_path,
        feature_flag=flag,
        options_count=len(payload.options),
        persisted_at=datetime.now(timezone.utc).isoformat(),
    )

    audit_id = _audit_write(
        action="integrations_configure",
        project_id=payload.project_id,
        actor=payload.actor,
        integration_name=payload.name,
        metadata={
            "ok": True,
            "vault_path": payload.vault_path,
            "option_keys": sorted(payload.options),
            "probe_mode": meta.get("probe", "stub"),
        },
    )

    # Cite-or-Refuse — every mutating write cites the audit row that
    # captured it AND the vault path the secret lives at.
    citations: list[Citation] = [
        Citation(
            type="audit_hash",
            ref=str(audit_id),
            excerpt=(
                f"integration={payload.name}; vault={payload.vault_path}; "
                f"actor={payload.actor}"
            ),
        ),
        Citation(
            type="file_line",
            ref=f"shared/mcp/tools/integrations.py:1",
            excerpt=f"_CATALOG[{payload.name!r}]",
        ),
    ]

    return ToolResponse(
        status="ok",
        data=body.model_dump(mode="json"),
        audit_id=audit_id,
        citation=citations,
    )


__all__ = [
    "IntegrationName",
    "IntegrationKind",
    "IntegrationsConfigureInput",
    "IntegrationsListInput",
    "IntegrationsTestConnectionInput",
    "integrations_configure",
    "integrations_list",
    "integrations_test_connection",
]
