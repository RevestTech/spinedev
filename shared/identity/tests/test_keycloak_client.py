"""Tests for ``shared.identity.keycloak_client``.

Uses a mocked async HTTP client so no real Keycloak is required. JWT
verification tests use a generated RS256 keypair when ``pyjwt[crypto]`` is
available; otherwise verification-path tests skip.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import pytest

from shared.identity.keycloak_client import (
    DEFAULT_JWKS_TTL_SECONDS,
    InvalidTokenError,
    JWKSFetchError,
    KeycloakClient,
)


# ---------------------------------------------------------------------------
# Fake httpx client
# ---------------------------------------------------------------------------


class _Resp:
    """Minimal stand-in for ``httpx.Response``."""

    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        if isinstance(self._payload, (dict, list)):
            return self._payload
        return json.loads(self._payload)


class FakeHttpClient:
    """Async stub that returns canned responses keyed by URL."""

    def __init__(
        self,
        get_responses: dict[str, _Resp] | None = None,
        post_responses: dict[str, _Resp] | None = None,
    ) -> None:
        self.get_responses = get_responses or {}
        self.post_responses = post_responses or {}
        self.get_calls: list[tuple[str, dict[str, str] | None]] = []
        self.post_calls: list[tuple[str, dict[str, Any], tuple[str, str] | None]] = []

    async def get(
        self, url: str, headers: dict[str, str] | None = None
    ) -> _Resp:
        self.get_calls.append((url, headers))
        if url not in self.get_responses:
            return _Resp(404, {"error": "not_found"})
        return self.get_responses[url]

    async def post(
        self,
        url: str,
        data: dict[str, Any] | None = None,
        auth: tuple[str, str] | None = None,
    ) -> _Resp:
        self.post_calls.append((url, data or {}, auth))
        if url not in self.post_responses:
            return _Resp(404, {"error": "not_found"})
        return self.post_responses[url]

    async def aclose(self) -> None:
        return None


# ---------------------------------------------------------------------------
# Construction + URL composition
# ---------------------------------------------------------------------------


def test_default_urls_compose_correctly() -> None:
    c = KeycloakClient(
        base_url="http://keycloak:8080",
        realm="spine",
        client_id="hub",
    )
    assert c.realm_url == "http://keycloak:8080/realms/spine"
    assert c.jwks_url == "http://keycloak:8080/realms/spine/protocol/openid-connect/certs"
    assert c.token_url.endswith("/protocol/openid-connect/token")
    assert c.userinfo_url.endswith("/protocol/openid-connect/userinfo")
    assert c.introspect_url.endswith("/protocol/openid-connect/token/introspect")
    assert c.issuer == "http://keycloak:8080/realms/spine"
    assert c.audience == "hub"
    assert c.jwks_ttl_seconds == DEFAULT_JWKS_TTL_SECONDS


def test_base_url_trailing_slash_normalized() -> None:
    c = KeycloakClient(base_url="http://kc/", realm="r", client_id="h")
    assert c.realm_url == "http://kc/realms/r"


# ---------------------------------------------------------------------------
# JWKS fetch + cache
# ---------------------------------------------------------------------------


def test_jwks_caches_within_ttl() -> None:
    jwks_doc = {"keys": [{"kid": "k1", "kty": "RSA", "alg": "RS256"}]}
    fake = FakeHttpClient(
        get_responses={
            "http://kc/realms/r/protocol/openid-connect/certs": _Resp(200, jwks_doc),
        }
    )
    c = KeycloakClient(
        base_url="http://kc",
        realm="r",
        client_id="h",
        http_client=fake,
        jwks_ttl_seconds=600,
    )
    first = asyncio.run(c.jwks())
    second = asyncio.run(c.jwks())
    assert first == jwks_doc
    assert second == jwks_doc
    # Cached → only one HTTP call
    assert len(fake.get_calls) == 1


def test_jwks_force_refresh_bypasses_cache() -> None:
    jwks_doc = {"keys": [{"kid": "k1", "kty": "RSA"}]}
    fake = FakeHttpClient(
        get_responses={
            "http://kc/realms/r/protocol/openid-connect/certs": _Resp(200, jwks_doc),
        }
    )
    c = KeycloakClient(
        base_url="http://kc", realm="r", client_id="h", http_client=fake
    )
    asyncio.run(c.jwks())
    asyncio.run(c.jwks(force_refresh=True))
    assert len(fake.get_calls) == 2


def test_jwks_refetches_after_ttl_expires() -> None:
    jwks_doc = {"keys": [{"kid": "k1"}]}
    fake = FakeHttpClient(
        get_responses={
            "http://kc/realms/r/protocol/openid-connect/certs": _Resp(200, jwks_doc),
        }
    )
    c = KeycloakClient(
        base_url="http://kc",
        realm="r",
        client_id="h",
        http_client=fake,
        jwks_ttl_seconds=1,
    )
    asyncio.run(c.jwks())
    # Simulate TTL expiry
    c._jwks_fetched_at = time.time() - 10
    asyncio.run(c.jwks())
    assert len(fake.get_calls) == 2


def test_jwks_http_error_raises_jwks_fetch_error() -> None:
    fake = FakeHttpClient(
        get_responses={
            "http://kc/realms/r/protocol/openid-connect/certs": _Resp(500, {}),
        }
    )
    c = KeycloakClient(
        base_url="http://kc", realm="r", client_id="h", http_client=fake
    )
    with pytest.raises(JWKSFetchError):
        asyncio.run(c.jwks())


def test_jwks_malformed_payload_raises() -> None:
    fake = FakeHttpClient(
        get_responses={
            "http://kc/realms/r/protocol/openid-connect/certs": _Resp(
                200, {"not_keys": []}
            ),
        }
    )
    c = KeycloakClient(
        base_url="http://kc", realm="r", client_id="h", http_client=fake
    )
    with pytest.raises(JWKSFetchError):
        asyncio.run(c.jwks())


# ---------------------------------------------------------------------------
# verify_token
# ---------------------------------------------------------------------------


def test_verify_token_rejects_empty() -> None:
    c = KeycloakClient(base_url="http://kc", realm="r", client_id="h", http_client=FakeHttpClient())
    with pytest.raises(InvalidTokenError):
        asyncio.run(c.verify_token(""))


def test_verify_token_rejects_non_rs256() -> None:
    pyjwt = pytest.importorskip("jwt")
    token = pyjwt.encode({"sub": "x", "exp": 9999999999, "iat": 1}, "secret", algorithm="HS256")
    c = KeycloakClient(base_url="http://kc", realm="r", client_id="h", http_client=FakeHttpClient())
    with pytest.raises(InvalidTokenError) as exc:
        asyncio.run(c.verify_token(token))
    assert "RS256" in str(exc.value)


def test_verify_token_round_trip_with_rs256() -> None:
    pyjwt = pytest.importorskip("jwt")
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem_priv = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    pub_jwk_dict = json.loads(
        pyjwt.algorithms.RSAAlgorithm.to_jwk(key.public_key())
    )
    pub_jwk_dict.update({"kid": "test-kid", "alg": "RS256", "use": "sig"})

    now = int(time.time())
    token = pyjwt.encode(
        {
            "sub": "user-1",
            "email": "u@example.com",
            "iss": "http://kc/realms/r",
            "aud": "hub",
            "exp": now + 300,
            "iat": now,
            "preferred_username": "u",
            "realm_access": {"roles": ["user", "admin"]},
            "resource_access": {"hub": {"roles": ["editor"]}},
            "groups": ["/engineering"],
            "scope": "openid profile email",
        },
        pem_priv,
        algorithm="RS256",
        headers={"kid": "test-kid"},
    )

    fake = FakeHttpClient(
        get_responses={
            "http://kc/realms/r/protocol/openid-connect/certs": _Resp(
                200, {"keys": [pub_jwk_dict]}
            ),
        }
    )
    c = KeycloakClient(
        base_url="http://kc", realm="r", client_id="hub", http_client=fake
    )
    claims = asyncio.run(c.verify_token(token))
    assert claims.sub == "user-1"
    assert claims.email == "u@example.com"
    assert claims.realm_access["roles"] == ["user", "admin"]
    assert "openid" in claims.scope


def test_verify_token_expired_rejected() -> None:
    pyjwt = pytest.importorskip("jwt")
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem_priv = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    pub_jwk_dict = json.loads(
        pyjwt.algorithms.RSAAlgorithm.to_jwk(key.public_key())
    )
    pub_jwk_dict.update({"kid": "k", "alg": "RS256", "use": "sig"})

    token = pyjwt.encode(
        {
            "sub": "x",
            "iss": "http://kc/realms/r",
            "aud": "hub",
            "exp": int(time.time()) - 3600,
            "iat": int(time.time()) - 7200,
        },
        pem_priv,
        algorithm="RS256",
        headers={"kid": "k"},
    )

    fake = FakeHttpClient(
        get_responses={
            "http://kc/realms/r/protocol/openid-connect/certs": _Resp(
                200, {"keys": [pub_jwk_dict]}
            ),
        }
    )
    c = KeycloakClient(
        base_url="http://kc", realm="r", client_id="hub", http_client=fake
    )
    with pytest.raises(InvalidTokenError):
        asyncio.run(c.verify_token(token))


# ---------------------------------------------------------------------------
# userinfo + introspect
# ---------------------------------------------------------------------------


def test_userinfo_round_trip() -> None:
    fake = FakeHttpClient(
        get_responses={
            "http://kc/realms/r/protocol/openid-connect/userinfo": _Resp(
                200, {"sub": "u", "email": "u@x.com"}
            ),
        }
    )
    c = KeycloakClient(
        base_url="http://kc", realm="r", client_id="h", http_client=fake
    )
    result = asyncio.run(c.userinfo("tok"))
    assert result["sub"] == "u"
    assert fake.get_calls[0][1] == {"Authorization": "Bearer tok"}


def test_introspect_requires_client_secret() -> None:
    c = KeycloakClient(
        base_url="http://kc",
        realm="r",
        client_id="h",
        http_client=FakeHttpClient(),
    )
    with pytest.raises(RuntimeError):
        asyncio.run(c.introspect("tok"))


def test_introspect_round_trip() -> None:
    fake = FakeHttpClient(
        post_responses={
            "http://kc/realms/r/protocol/openid-connect/token/introspect": _Resp(
                200, {"active": True, "sub": "u"}
            ),
        }
    )
    c = KeycloakClient(
        base_url="http://kc",
        realm="r",
        client_id="h",
        client_secret="s",
        http_client=fake,
    )
    result = asyncio.run(c.introspect("tok"))
    assert result["active"] is True
    assert fake.post_calls[0][2] == ("h", "s")
