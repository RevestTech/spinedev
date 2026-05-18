"""Tests for ``shared.identity.middleware``.

Uses a mock ``KeycloakClient`` (no JWT decoding) to exercise header parsing
+ dependency wiring + error paths.
"""

from __future__ import annotations

import asyncio

import pytest

from shared.identity.keycloak_client import InvalidTokenError
from shared.identity.middleware import (
    AuthenticationError,
    bearer_token_from_header,
    current_user,
    get_keycloak_client,
    optional_user,
    set_keycloak_client,
)
from shared.identity.models import TokenClaims


# ---------------------------------------------------------------------------
# Mock client
# ---------------------------------------------------------------------------


class _MockKC:
    """Stand-in for KeycloakClient.verify_token."""

    def __init__(self, claims: TokenClaims | None = None, error: Exception | None = None) -> None:
        self.claims = claims
        self.error = error
        self.calls: list[str] = []

    async def verify_token(self, token: str) -> TokenClaims:
        self.calls.append(token)
        if self.error is not None:
            raise self.error
        assert self.claims is not None
        return self.claims


def _fresh_claims(sub: str = "u-1") -> TokenClaims:
    return TokenClaims(
        sub=sub,
        email="u@x.com",
        preferred_username="u",
        realm_access={"roles": ["user"]},
        scope="openid profile",
        exp=9999999999,
        iat=1,
    )


# ---------------------------------------------------------------------------
# bearer_token_from_header
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("Bearer abc.def.ghi", "abc.def.ghi"),
        ("bearer abc", "abc"),
        ("BEARER xyz", "xyz"),
        ("Bearer   spaced  ", "spaced"),
        ("Basic abc", None),
        ("Bearer", None),
        ("", None),
        (None, None),
        ("Bearer ", None),
    ],
)
def test_bearer_token_extraction(value: str | None, expected: str | None) -> None:
    assert bearer_token_from_header(value) == expected


# ---------------------------------------------------------------------------
# get / set keycloak_client
# ---------------------------------------------------------------------------


def test_get_keycloak_client_uninitialized_raises() -> None:
    set_keycloak_client(None)
    with pytest.raises(Exception) as exc:
        get_keycloak_client()
    # Either fastapi HTTPException or our shim — both have a .status_code attr.
    assert getattr(exc.value, "status_code", None) == 500


def test_set_and_get_keycloak_client_round_trip() -> None:
    mock = _MockKC(claims=_fresh_claims())
    set_keycloak_client(mock)  # type: ignore[arg-type]
    try:
        assert get_keycloak_client() is mock  # type: ignore[comparison-overlap]
    finally:
        set_keycloak_client(None)


# ---------------------------------------------------------------------------
# current_user
# ---------------------------------------------------------------------------


def test_current_user_happy_path() -> None:
    mock = _MockKC(claims=_fresh_claims("subject-42"))
    set_keycloak_client(mock)  # type: ignore[arg-type]
    try:
        user = asyncio.run(current_user(authorization="Bearer xyz.token"))
        assert user.id == "subject-42"
        assert user.email == "u@x.com"
        assert "user" in user.roles
        assert "openid" in user.scopes
        assert mock.calls == ["xyz.token"]
    finally:
        set_keycloak_client(None)


def test_current_user_missing_header_raises_401() -> None:
    mock = _MockKC(claims=_fresh_claims())
    set_keycloak_client(mock)  # type: ignore[arg-type]
    try:
        with pytest.raises(AuthenticationError) as exc:
            asyncio.run(current_user(authorization=""))
        assert getattr(exc.value, "status_code", None) == 401
    finally:
        set_keycloak_client(None)


def test_current_user_malformed_header_raises_401() -> None:
    mock = _MockKC(claims=_fresh_claims())
    set_keycloak_client(mock)  # type: ignore[arg-type]
    try:
        with pytest.raises(AuthenticationError):
            asyncio.run(current_user(authorization="Basic abc"))
    finally:
        set_keycloak_client(None)


def test_current_user_invalid_token_raises_401() -> None:
    mock = _MockKC(error=InvalidTokenError("expired"))
    set_keycloak_client(mock)  # type: ignore[arg-type]
    try:
        with pytest.raises(AuthenticationError) as exc:
            asyncio.run(current_user(authorization="Bearer bad.token"))
        assert "expired" in str(exc.value.detail) or "expired" in str(exc.value)
    finally:
        set_keycloak_client(None)


# ---------------------------------------------------------------------------
# optional_user
# ---------------------------------------------------------------------------


def test_optional_user_none_when_no_header() -> None:
    mock = _MockKC(claims=_fresh_claims())
    set_keycloak_client(mock)  # type: ignore[arg-type]
    try:
        result = asyncio.run(optional_user(authorization=None))
        assert result is None
    finally:
        set_keycloak_client(None)


def test_optional_user_still_validates_when_header_present() -> None:
    mock = _MockKC(error=InvalidTokenError("bad sig"))
    set_keycloak_client(mock)  # type: ignore[arg-type]
    try:
        with pytest.raises(AuthenticationError):
            asyncio.run(optional_user(authorization="Bearer bad"))
    finally:
        set_keycloak_client(None)


def test_optional_user_happy_path() -> None:
    mock = _MockKC(claims=_fresh_claims("x"))
    set_keycloak_client(mock)  # type: ignore[arg-type]
    try:
        u = asyncio.run(optional_user(authorization="Bearer ok"))
        assert u is not None and u.id == "x"
    finally:
        set_keycloak_client(None)
