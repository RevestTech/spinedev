"""Tests for the Wave 6 Stream J extensions on ``ToolRequest`` (#30).

Covers:
  * Backward compat — existing payloads (no new fields) still validate.
  * ``feature_flag_required`` round-trips and rejects empty strings.
  * ``actor_token_claims`` accepts arbitrary dict-shaped Keycloak claims.
  * ``extra='forbid'`` still rejects unknown fields.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.mcp.schemas import ToolRequest


def test_minimal_request_still_validates() -> None:
    req = ToolRequest(project_id="p1", actor="engineer")
    assert req.project_id == "p1"
    assert req.feature_flag_required is None
    assert req.actor_token_claims is None


def test_feature_flag_required_roundtrips() -> None:
    req = ToolRequest(
        project_id="p1", actor="engineer",
        feature_flag_required="integration_github",
    )
    assert req.feature_flag_required == "integration_github"
    dumped = req.model_dump(mode="json")
    assert dumped["feature_flag_required"] == "integration_github"


def test_feature_flag_required_rejects_empty_string() -> None:
    with pytest.raises(ValidationError):
        ToolRequest(
            project_id="p1", actor="engineer",
            feature_flag_required="",
        )


def test_actor_token_claims_accepts_dict() -> None:
    claims = {
        "sub": "u-1",
        "email": "alice@example.com",
        "realm_access": {"roles": ["hub-admin", "user"]},
        "scope": "openid profile",
        "exp": 9_999_999_999,
    }
    req = ToolRequest(
        project_id="p1", actor="hub_admin",
        actor_token_claims=claims,
    )
    assert req.actor_token_claims == claims
    assert req.actor_token_claims["realm_access"]["roles"] == ["hub-admin", "user"]


def test_unknown_fields_still_rejected() -> None:
    with pytest.raises(ValidationError):
        ToolRequest(
            project_id="p1", actor="engineer",
            not_a_real_field="oops",  # type: ignore[call-arg]
        )


def test_both_new_fields_optional_independently() -> None:
    """flag-only and claims-only requests both validate."""
    a = ToolRequest(
        project_id="p1", actor="x",
        feature_flag_required="federation",
    )
    assert a.actor_token_claims is None

    b = ToolRequest(
        project_id="p1", actor="x",
        actor_token_claims={"sub": "u-2"},
    )
    assert b.feature_flag_required is None
