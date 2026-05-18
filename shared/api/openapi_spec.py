"""Heavier OpenAPI 3.x spec emitter for the Spine Hub REST API (V3 #30).

FastAPI generates a usable default spec from route annotations, but the
Spine contract has additional cross-cutting concerns the default skips:

1. **Version stamp** — every operation must carry the ``X-Spine-API-Version``
   response header so clients can sanity-check the served version against
   their cached client SDK.
2. **Standard error envelopes** — 401, 402 (feature_disabled), 403,
   422 (validation), 429 (rate-limited), 500 (internal) must appear
   under every operation that can plausibly emit them. We add them via
   reusable ``components.responses`` entries so the spec stays small.
3. **Reusable Citation schema** — the Cite-or-Refuse contract (#12)
   demands that any verify-class endpoint can declare its citation
   shape via ``$ref``. We register the Pydantic ``Citation`` model as
   ``components.schemas.Citation``.
4. **Server URL templates** — per #17 Spine deploys in 4 shapes (laptop /
   BYOC / customer-cloud / on-prem). The spec lists all four as
   ``servers[]`` entries with variable placeholders, so the generated
   client SDKs work across shapes without a recompile.
5. **Security schemes** — Keycloak OIDC Bearer AND the SPA cookie
   session, both registered in ``components.securitySchemes`` with the
   discovery URL templated against ``{keycloak_base}`` and ``{realm}``.

This module exposes :func:`build_openapi` which a FastAPI app calls in
place of ``app.openapi()`` once at startup; the result is cached on the
app instance. The caller pattern is::

    from shared.api.openapi_spec import install_openapi_spec

    install_openapi_spec(app)  # overrides app.openapi
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Final, Optional

try:  # pragma: no cover - guarded for py_compile
    from fastapi import FastAPI
    from fastapi.openapi.utils import get_openapi
except Exception:  # pragma: no cover
    FastAPI = object  # type: ignore[assignment,misc]

    def get_openapi(**_: Any) -> dict[str, Any]:  # type: ignore[no-redef]
        return {"openapi": "3.1.0", "info": {}, "paths": {}}


from shared.api.versioning import (
    API_V2_PREFIX,
    API_V3_PREFIX,
    CURRENT_PUBLIC_PREFIX,
    SUPPORTED_PREFIXES,
)

logger = logging.getLogger("spine.api.openapi")


# ---------------------------------------------------------------------------
# Constants — versioning + server templates
# ---------------------------------------------------------------------------

#: OpenAPI dialect — 3.1 because we need ``examples`` on parameters and
#: ``oneOf`` + ``$ref`` together for the error envelope union.
OPENAPI_VERSION: Final[str] = "3.1.0"

#: The X-Spine-API-Version response header value we stamp on every op.
#: Bumped when CURRENT_PUBLIC_PREFIX rotates (e.g. v2 -> v3).
SPINE_API_VERSION_HEADER_VALUE: Final[str] = CURRENT_PUBLIC_PREFIX.lstrip("/").split("/")[-1]

#: Deployment shape templates per #17. The variables let the generated
#: SDKs swap base URLs at runtime without a rebuild.
SERVER_TEMPLATES: Final[list[dict[str, Any]]] = [
    {
        "url": "http://localhost:{port}",
        "description": "Laptop / dev — single-node Hub on localhost.",
        "variables": {
            "port": {"default": "8088", "description": "Hub HTTP port."},
        },
    },
    {
        "url": "https://{hub_host}",
        "description": "BYOC — customer-owned cloud, customer DNS.",
        "variables": {
            "hub_host": {
                "default": "hub.example.com",
                "description": "Customer-controlled Hub hostname.",
            },
        },
    },
    {
        "url": "https://{hub_host}.spine.{tenant}.cloud",
        "description": "Customer-cloud — Spine-managed under customer subdomain.",
        "variables": {
            "hub_host": {"default": "hub", "description": "Hub subdomain."},
            "tenant": {
                "default": "acme",
                "description": "Customer tenant slug.",
            },
        },
    },
    {
        "url": "https://{hub_host}.{onprem_zone}",
        "description": "On-prem — fully air-gappable per #17 (v1.1 air-gap).",
        "variables": {
            "hub_host": {"default": "spine-hub", "description": "Hub hostname."},
            "onprem_zone": {
                "default": "internal.example.corp",
                "description": "Internal DNS zone.",
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Reusable schema fragments
# ---------------------------------------------------------------------------


def _citation_schema() -> dict[str, Any]:
    """JSON Schema for the Cite-or-Refuse :class:`Citation` model (#12).

    Built by hand (not from Pydantic) so this module has no Pydantic
    import-time dependency on ``shared.mcp.schemas`` — keeps the API
    layer linkable in environments where the MCP package isn't installed
    (rare but possible during partial-install dev loops).
    """
    return {
        "type": "object",
        "title": "Citation",
        "description": (
            "One unit of supporting evidence for a verify-class tool "
            "response. Per V3 #12 Cite-or-Refuse, any tool tagged "
            "requires_citation=True MUST attach at least one Citation."
        ),
        "additionalProperties": False,
        "required": ["type", "ref"],
        "properties": {
            "type": {
                "type": "string",
                "enum": ["kg_node", "file_line", "audit_hash"],
                "description": "Evidence class.",
            },
            "ref": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "Stable reference. kg_node -> spine_kg node_id; "
                    "file_line -> 'path:line[:col]'; audit_hash -> "
                    "spine_audit.event content_hash."
                ),
            },
            "excerpt": {
                "type": ["string", "null"],
                "description": "Optional short verbatim excerpt.",
            },
        },
    }


def _error_envelope_schema() -> dict[str, Any]:
    """Generic structured-error body shape used by 401/402/403/422/429/500."""
    return {
        "type": "object",
        "title": "ErrorEnvelope",
        "description": "Standard Spine error response shape.",
        "additionalProperties": True,
        "required": ["error_code", "message"],
        "properties": {
            "error_code": {
                "type": "string",
                "description": "Stable machine-readable error code.",
                "example": "feature_disabled",
            },
            "message": {
                "type": "string",
                "description": "Human-readable explanation.",
            },
            "feature_flag": {
                "type": "string",
                "description": (
                    "Set on 402 (feature_disabled) + 429 (rate_limited) "
                    "to identify the gating capability."
                ),
            },
            "upgrade_path": {
                "type": "string",
                "description": "Set on 402; SPA route for the upgrade UI.",
            },
            "retry_after_seconds": {
                "type": "integer",
                "minimum": 0,
                "description": (
                    "Set on 429 alongside the Retry-After header."
                ),
            },
        },
    }


def _standard_responses() -> dict[str, dict[str, Any]]:
    """The reusable ``components.responses`` entries every op may $ref."""
    err = {"$ref": "#/components/schemas/ErrorEnvelope"}
    json_err = {"application/json": {"schema": err}}
    return {
        "Unauthorized": {
            "description": "Bearer/cookie auth missing or invalid (#25).",
            "content": json_err,
        },
        "FeatureDisabled": {
            "description": (
                "402 Payment Required — feature not on this licence tier (#23)."
            ),
            "content": json_err,
        },
        "Forbidden": {
            "description": "Authenticated but lacks the required role/scope.",
            "content": json_err,
        },
        "ValidationError": {
            "description": "422 — request payload failed schema validation.",
            "content": json_err,
        },
        "RateLimited": {
            "description": (
                "429 Too Many Requests — per-org quota exceeded (#30 + #23). "
                "Includes Retry-After header."
            ),
            "headers": {
                "Retry-After": {
                    "description": "Seconds until the next token refills.",
                    "schema": {"type": "integer", "minimum": 1},
                },
                "X-Spine-Rate-Limit-Flag": {
                    "description": "Feature flag whose quota was exceeded.",
                    "schema": {"type": "string"},
                },
            },
            "content": json_err,
        },
        "InternalError": {
            "description": "500 — unexpected server error; check audit log.",
            "content": json_err,
        },
    }


def _security_schemes() -> dict[str, dict[str, Any]]:
    """Keycloak OIDC bearer + SPA cookie session (#25)."""
    return {
        "KeycloakBearer": {
            "type": "openIdConnect",
            "description": (
                "Keycloak-issued OIDC Bearer access token. Verified "
                "against the realm JWKS per #25. The discovery URL "
                "below is templated against the customer's Keycloak."
            ),
            "openIdConnectUrl": (
                "{keycloak_base}/realms/{realm}/.well-known/openid-configuration"
            ),
        },
        "SpineSessionCookie": {
            "type": "apiKey",
            "in": "cookie",
            "name": "spine_session",
            "description": (
                "SPA browser cookie minted by /api/v2/auth/callback; "
                "HMAC-signed with a vault-fetched key per #9. The "
                "OidcCookieMiddleware translates this back into a "
                "Bearer header before downstream dependencies run."
            ),
        },
    }


# ---------------------------------------------------------------------------
# Build the spec
# ---------------------------------------------------------------------------


def _stamp_version_header_on_operations(paths: dict[str, Any]) -> None:
    """Append ``X-Spine-API-Version`` to every response object on every op.

    Mutates ``paths`` in place. The header is added to EXISTING response
    entries (default + any explicit codes) AND to a synthetic ``default``
    entry if the operation declared none. This keeps the spec valid
    while ensuring no operation forgets the header contract.
    """
    header_def = {
        "description": (
            "Echoes the served API version (e.g. 'v2'). Clients should "
            "compare against the version their SDK was generated for and "
            "log a warning on mismatch."
        ),
        "schema": {"type": "string", "example": SPINE_API_VERSION_HEADER_VALUE},
    }
    for _path, item in paths.items():
        if not isinstance(item, dict):
            continue
        for method, op in item.items():
            if method.startswith("x-") or not isinstance(op, dict):
                continue
            responses = op.setdefault("responses", {})
            if not responses:
                responses["default"] = {
                    "description": "Default response.",
                }
            for _code, resp in responses.items():
                if not isinstance(resp, dict):
                    continue
                headers = resp.setdefault("headers", {})
                headers.setdefault("X-Spine-API-Version", header_def)


def _attach_standard_errors(paths: dict[str, Any]) -> None:
    """Add reusable ``$ref`` error responses to operations missing them."""
    refs = {
        "401": {"$ref": "#/components/responses/Unauthorized"},
        "402": {"$ref": "#/components/responses/FeatureDisabled"},
        "403": {"$ref": "#/components/responses/Forbidden"},
        "422": {"$ref": "#/components/responses/ValidationError"},
        "429": {"$ref": "#/components/responses/RateLimited"},
        "500": {"$ref": "#/components/responses/InternalError"},
    }
    for _path, item in paths.items():
        if not isinstance(item, dict):
            continue
        for method, op in item.items():
            if method.startswith("x-") or not isinstance(op, dict):
                continue
            responses = op.setdefault("responses", {})
            for code, ref in refs.items():
                # Do not clobber operation-specific error documentation.
                responses.setdefault(code, ref)


def build_openapi(
    app: "FastAPI",
    *,
    title: Optional[str] = None,
    version: Optional[str] = None,
    description: Optional[str] = None,
) -> dict[str, Any]:
    """Generate the heavier Spine OpenAPI spec dict.

    Layered on top of FastAPI's default ``get_openapi``:

    1. Force ``openapi`` to :data:`OPENAPI_VERSION` (3.1).
    2. Inject server templates (#17), security schemes (#25), Citation
       schema (#12), and the reusable error envelope (#30).
    3. Stamp every operation with ``X-Spine-API-Version`` (#30).
    4. Add reusable ``$ref`` error responses to every operation (#30).

    Caller normally uses :func:`install_openapi_spec` instead of calling
    this directly.
    """
    base = get_openapi(
        title=title or getattr(app, "title", "Spine Hub REST API"),
        version=version or getattr(app, "version", "0.3.0"),
        description=description or getattr(app, "description", ""),
        routes=getattr(app, "routes", []),
    )

    base["openapi"] = OPENAPI_VERSION

    # 1. Servers — replace FastAPI's host-relative default.
    base["servers"] = list(SERVER_TEMPLATES)

    # 2. Components — schemas + responses + security schemes.
    components = base.setdefault("components", {})
    schemas = components.setdefault("schemas", {})
    schemas.setdefault("Citation", _citation_schema())
    schemas.setdefault("ErrorEnvelope", _error_envelope_schema())
    responses = components.setdefault("responses", {})
    for name, body in _standard_responses().items():
        responses.setdefault(name, body)
    sec_schemes = components.setdefault("securitySchemes", {})
    for name, body in _security_schemes().items():
        sec_schemes.setdefault(name, body)

    # 3. Global security — Bearer is the default; cookie listed as
    # alternative so the SPA flow passes spec validation. Per-op
    # overrides win.
    base.setdefault(
        "security",
        [{"KeycloakBearer": []}, {"SpineSessionCookie": []}],
    )

    # 4. Per-operation polish — header stamp + error refs.
    paths = base.setdefault("paths", {})
    _stamp_version_header_on_operations(paths)
    _attach_standard_errors(paths)

    # 5. Spine-specific x-* extensions for downstream tooling.
    base["x-spine-supported-versions"] = list(SUPPORTED_PREFIXES)
    base["x-spine-reserved-versions"] = [API_V3_PREFIX]
    base["x-spine-current-version"] = API_V2_PREFIX

    return base


def install_openapi_spec(app: "FastAPI") -> "FastAPI":
    """Override ``app.openapi`` with the cached heavier spec.

    Idempotent — calling twice is fine. The cache lives on the app
    instance so a hot-reload picks up route changes via app rebuild.
    """
    cached: dict[str, Any] = {}

    def _openapi() -> dict[str, Any]:
        if cached:
            return cached
        spec = build_openapi(app)
        cached.update(spec)
        # FastAPI also caches on ``app.openapi_schema`` — mirror so other
        # consumers (Swagger UI, /openapi.json) see the same dict.
        try:
            app.openapi_schema = spec  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover
            pass
        return cached

    try:
        app.openapi = _openapi  # type: ignore[assignment]
    except Exception:  # pragma: no cover
        logger.warning("openapi_install_failed_attribute_assignment")
    return app


__all__ = [
    "OPENAPI_VERSION",
    "SERVER_TEMPLATES",
    "SPINE_API_VERSION_HEADER_VALUE",
    "build_openapi",
    "install_openapi_spec",
]
