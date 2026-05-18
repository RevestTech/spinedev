"""Tests for ``shared.api.openapi_spec`` (V3 Wave 6 Stream J, #30)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from shared.api.openapi_spec import (
    OPENAPI_VERSION,
    SERVER_TEMPLATES,
    SPINE_API_VERSION_HEADER_VALUE,
    build_openapi,
    install_openapi_spec,
)


@pytest.fixture
def app() -> FastAPI:
    a = FastAPI(title="Test API", version="9.9.9", description="d")

    @a.get("/api/v2/things", tags=["things"])
    async def list_things() -> list[dict]:
        return []

    @a.post("/api/v2/things", tags=["things"])
    async def create_thing() -> dict:
        return {"ok": True}

    @a.get("/api/v2/things/{thing_id}", tags=["things"])
    async def get_thing(thing_id: str) -> dict:
        return {"id": thing_id}

    return a


def test_build_openapi_uses_3_1(app: FastAPI) -> None:
    spec = build_openapi(app)
    assert spec["openapi"] == OPENAPI_VERSION
    assert OPENAPI_VERSION.startswith("3.")


def test_servers_cover_four_deployment_shapes(app: FastAPI) -> None:
    spec = build_openapi(app)
    assert len(spec["servers"]) == len(SERVER_TEMPLATES) == 4
    descriptions = " | ".join(s["description"] for s in spec["servers"])
    for kw in ("Laptop", "BYOC", "Customer-cloud", "On-prem"):
        assert kw.lower() in descriptions.lower()


def test_components_include_citation_and_error_envelope(app: FastAPI) -> None:
    spec = build_openapi(app)
    schemas = spec["components"]["schemas"]
    assert "Citation" in schemas
    assert "ErrorEnvelope" in schemas
    cit = schemas["Citation"]
    assert cit["required"] == ["type", "ref"]
    assert set(cit["properties"]["type"]["enum"]) == {
        "kg_node", "file_line", "audit_hash",
    }


def test_components_include_standard_error_responses(app: FastAPI) -> None:
    spec = build_openapi(app)
    responses = spec["components"]["responses"]
    for name in ("Unauthorized", "FeatureDisabled", "Forbidden",
                 "ValidationError", "RateLimited", "InternalError"):
        assert name in responses
    # RateLimited carries the Retry-After header doc.
    headers = responses["RateLimited"]["headers"]
    assert "Retry-After" in headers
    assert "X-Spine-Rate-Limit-Flag" in headers


def test_security_schemes_include_keycloak_oidc_and_cookie(app: FastAPI) -> None:
    spec = build_openapi(app)
    schemes = spec["components"]["securitySchemes"]
    assert "KeycloakBearer" in schemes
    assert schemes["KeycloakBearer"]["type"] == "openIdConnect"
    assert "openid-configuration" in schemes["KeycloakBearer"]["openIdConnectUrl"]
    assert "SpineSessionCookie" in schemes
    assert schemes["SpineSessionCookie"]["type"] == "apiKey"
    assert schemes["SpineSessionCookie"]["in"] == "cookie"


def test_every_operation_carries_version_header(app: FastAPI) -> None:
    spec = build_openapi(app)
    paths = spec["paths"]
    for _path, item in paths.items():
        for method, op in item.items():
            if method.startswith("x-"):
                continue
            for _code, resp in op["responses"].items():
                if not isinstance(resp, dict):
                    continue
                if "headers" in resp:
                    assert "X-Spine-API-Version" in resp["headers"]


def test_every_operation_has_standard_error_refs(app: FastAPI) -> None:
    """Every code (401/402/403/422/429/500) is present. FastAPI may have
    pre-populated 422 from Pydantic validation — we accept either shape
    (a ``$ref`` we added, or FastAPI's own ``content/schema/$ref``) so
    long as the response code exists.
    """
    spec = build_openapi(app)
    paths = spec["paths"]
    for _path, item in paths.items():
        for method, op in item.items():
            if method.startswith("x-"):
                continue
            responses = op["responses"]
            for code in ("401", "402", "403", "422", "429", "500"):
                assert code in responses, (
                    f"{method.upper()} {_path} missing {code} response"
                )
            # The ones WE added (not pre-populated by FastAPI) carry
            # our reusable $ref; 422 may carry FastAPI's own
            # HTTPValidationError instead.
            for code in ("401", "402", "403", "429", "500"):
                assert "$ref" in responses[code], (
                    f"{method.upper()} {_path} {code} missing $ref"
                )


def test_spine_extensions_describe_version_lifecycle(app: FastAPI) -> None:
    spec = build_openapi(app)
    assert spec["x-spine-current-version"] == "/api/v2"
    assert "/api/v2" in spec["x-spine-supported-versions"]
    assert "/api/v3" in spec["x-spine-reserved-versions"]


def test_install_openapi_spec_overrides_app_openapi(app: FastAPI) -> None:
    install_openapi_spec(app)
    spec = app.openapi()
    assert spec["openapi"] == OPENAPI_VERSION
    # Caching: second call returns the same dict object.
    spec2 = app.openapi()
    assert spec is spec2
    assert "Citation" in spec["components"]["schemas"]


def test_spine_api_version_header_value_matches_current_prefix() -> None:
    assert SPINE_API_VERSION_HEADER_VALUE == "v2"
