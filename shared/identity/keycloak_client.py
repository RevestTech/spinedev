"""
shared/identity/keycloak_client.py
==================================

Async OIDC client for the Spine-embedded Keycloak realm.

Responsibilities:

* Fetch + cache the realm JWKS (signing keys) — TTL ``DEFAULT_JWKS_TTL_SECONDS``.
* Verify RS256-signed Bearer JWTs against the cached JWKS, validating
  ``iss`` / ``aud`` / ``exp`` / ``nbf`` per RFC 7519.
* Wrap the standard OIDC ``/userinfo`` and ``/token/introspect`` endpoints.

What this client **does NOT do** (and never should):

* Resource-owner password-credential grant (deprecated; #25 forbids).
* SAML / SCIM / social-login glue (Keycloak owns all of that — #25).
* Cookie/session management (Wave 3 concern).

Dependencies (declared in ``shared/identity/README.md`` — not added to
``requirements.txt`` by this agent per Wave 0 scope rules):

* ``pyjwt[crypto]`` >= 2.8 — JWT decode + RS256 verification.
* ``httpx`` >= 0.27 — async HTTP client for token / userinfo / JWKS calls.

The client is intentionally constructor-injectable so tests can pass a
mocked ``httpx.AsyncClient``. Production callers should use one
process-wide instance (see ``shared/identity/middleware.py``).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import urljoin

try:  # pragma: no cover - import guarded so py_compile works in any env
    import httpx
except Exception:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

try:  # pragma: no cover
    import jwt as pyjwt
    from jwt import PyJWKClient
except Exception:  # pragma: no cover
    pyjwt = None  # type: ignore[assignment]
    PyJWKClient = None  # type: ignore[assignment,misc]

from .models import TokenClaims


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

DEFAULT_JWKS_TTL_SECONDS: int = 300  # 5 minutes — matches OIDC convention
DEFAULT_HTTP_TIMEOUT_SECONDS: float = 5.0
DEFAULT_LEEWAY_SECONDS: int = 30  # clock-skew tolerance on exp/nbf


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class IdentityError(Exception):
    """Base for all identity-package errors."""


class JWKSFetchError(IdentityError):
    """Raised when the realm JWKS endpoint cannot be loaded."""


class InvalidTokenError(IdentityError):
    """Raised when a Bearer token fails signature/claim verification."""


# ---------------------------------------------------------------------------
# OIDC client
# ---------------------------------------------------------------------------


class KeycloakClient:
    """Minimal async OIDC client targeting a single Keycloak realm.

    Parameters
    ----------
    base_url:
        Keycloak base URL, e.g. ``https://kc.example.com`` or
        ``http://keycloak:8080``. Trailing slash optional.
    realm:
        Realm name, e.g. ``spine``.
    client_id:
        OIDC client_id Spine Hub was registered as inside the realm.
    client_secret:
        Confidential-client secret. Required for ``introspect``;
        optional for ``verify_token`` (which only needs JWKS).
    audience:
        Expected ``aud`` claim. Defaults to ``client_id``.
    issuer:
        Expected ``iss`` claim. Defaults to
        ``{base_url}/realms/{realm}``.
    jwks_ttl_seconds:
        How long to cache the JWKS document. Defaults to 5 min.
    http_client:
        Optional pre-constructed ``httpx.AsyncClient`` — for tests.
    """

    def __init__(
        self,
        base_url: str,
        realm: str,
        client_id: str,
        *,
        client_secret: str | None = None,
        audience: str | None = None,
        issuer: str | None = None,
        jwks_ttl_seconds: int = DEFAULT_JWKS_TTL_SECONDS,
        leeway_seconds: int = DEFAULT_LEEWAY_SECONDS,
        http_client: Any | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.realm = realm
        self.client_id = client_id
        self.client_secret = client_secret
        self.audience = audience or client_id
        self.issuer = issuer or urljoin(self.base_url, f"realms/{realm}")
        self.jwks_ttl_seconds = jwks_ttl_seconds
        self.leeway_seconds = leeway_seconds

        self._http = http_client  # injectable for tests
        self._jwks: dict[str, Any] | None = None
        self._jwks_fetched_at: float = 0.0
        self._jwks_lock = asyncio.Lock()

    # ------------------------------------------------------------------ URLs

    @property
    def realm_url(self) -> str:
        """Base URL for the configured realm."""
        return urljoin(self.base_url, f"realms/{self.realm}")

    @property
    def jwks_url(self) -> str:
        """JWKS (signing keys) endpoint for the realm."""
        return f"{self.realm_url}/protocol/openid-connect/certs"

    @property
    def token_url(self) -> str:
        """Token endpoint (only used for client-credentials + introspect)."""
        return f"{self.realm_url}/protocol/openid-connect/token"

    @property
    def userinfo_url(self) -> str:
        """OIDC userinfo endpoint."""
        return f"{self.realm_url}/protocol/openid-connect/userinfo"

    @property
    def introspect_url(self) -> str:
        """RFC 7662 token introspection endpoint."""
        return f"{self.realm_url}/protocol/openid-connect/token/introspect"

    # ---------------------------------------------------------------- helpers

    def _client(self) -> Any:
        """Return an ``httpx.AsyncClient`` — lazily constructed."""
        if self._http is not None:
            return self._http
        if httpx is None:
            raise RuntimeError(
                "httpx is not installed; install `httpx>=0.27` "
                "(see shared/identity/README.md)"
            )
        self._http = httpx.AsyncClient(timeout=DEFAULT_HTTP_TIMEOUT_SECONDS)
        return self._http

    async def aclose(self) -> None:
        """Close the underlying HTTP client (no-op if injected)."""
        if self._http is not None and hasattr(self._http, "aclose"):
            try:
                await self._http.aclose()
            except Exception:  # pragma: no cover - best-effort
                pass

    # --------------------------------------------------------------- JWKS

    async def jwks(self, *, force_refresh: bool = False) -> dict[str, Any]:
        """Return the realm JWKS dict, refreshing when the TTL elapses.

        Refresh strategy: lazy + TTL-bounded. We do not poll. A forced refresh
        is triggered on ``kid``-not-found in ``verify_token`` so rotated keys
        propagate within one failed verification rather than one full TTL.
        """
        now = time.time()
        if (
            not force_refresh
            and self._jwks is not None
            and (now - self._jwks_fetched_at) < self.jwks_ttl_seconds
        ):
            return self._jwks

        async with self._jwks_lock:
            # Re-check inside the lock (double-checked locking).
            if (
                not force_refresh
                and self._jwks is not None
                and (time.time() - self._jwks_fetched_at) < self.jwks_ttl_seconds
            ):
                return self._jwks

            client = self._client()
            try:
                resp = await client.get(self.jwks_url)
            except Exception as exc:
                raise JWKSFetchError(
                    f"Could not reach JWKS endpoint {self.jwks_url}: {exc}"
                ) from exc

            status = getattr(resp, "status_code", 0)
            if status != 200:
                raise JWKSFetchError(
                    f"JWKS endpoint {self.jwks_url} returned HTTP {status}"
                )

            try:
                payload = resp.json()
            except Exception as exc:
                raise JWKSFetchError(
                    f"JWKS endpoint {self.jwks_url} returned non-JSON: {exc}"
                ) from exc

            if not isinstance(payload, dict) or "keys" not in payload:
                raise JWKSFetchError(
                    f"JWKS endpoint {self.jwks_url} returned malformed payload"
                )

            self._jwks = payload
            self._jwks_fetched_at = time.time()
            return self._jwks

    def _select_signing_key(self, jwks: dict[str, Any], kid: str | None) -> Any:
        """Pick the RS256 key whose ``kid`` matches the JWT header."""
        if pyjwt is None:
            raise RuntimeError(
                "pyjwt is not installed; install `pyjwt[crypto]>=2.8` "
                "(see shared/identity/README.md)"
            )
        keys = jwks.get("keys", []) or []
        candidates = [k for k in keys if not kid or k.get("kid") == kid]
        if not candidates:
            raise InvalidTokenError(
                f"No JWKS key matches token kid={kid!r}"
            )
        jwk = candidates[0]
        return pyjwt.algorithms.RSAAlgorithm.from_jwk(jwk)

    # ----------------------------------------------------------- verify_token

    async def verify_token(self, token: str) -> TokenClaims:
        """Validate ``token`` (Bearer JWT) and return parsed claims.

        Raises ``InvalidTokenError`` on any failure: bad signature, wrong
        issuer, wrong audience, expired, malformed, or unknown ``kid``.
        Rotated-key safety: if first JWKS lookup misses the ``kid``, the
        JWKS is force-refreshed once and retried.
        """
        if pyjwt is None:
            raise RuntimeError(
                "pyjwt is not installed; install `pyjwt[crypto]>=2.8` "
                "(see shared/identity/README.md)"
            )
        if not token or not isinstance(token, str):
            raise InvalidTokenError("Empty or non-string token")

        try:
            unverified_header = pyjwt.get_unverified_header(token)
        except Exception as exc:
            raise InvalidTokenError(f"Malformed JWT header: {exc}") from exc

        kid = unverified_header.get("kid")
        alg = unverified_header.get("alg")
        if alg != "RS256":
            raise InvalidTokenError(
                f"Unsupported JWT alg {alg!r}; Spine only accepts RS256"
            )

        jwks = await self.jwks()
        try:
            key = self._select_signing_key(jwks, kid)
        except InvalidTokenError:
            # Rotated-key safety: try once with a forced refresh.
            jwks = await self.jwks(force_refresh=True)
            key = self._select_signing_key(jwks, kid)

        try:
            payload: dict[str, Any] = pyjwt.decode(
                token,
                key=key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.leeway_seconds,
                options={"require": ["exp", "iat", "sub"]},
            )
        except Exception as exc:
            raise InvalidTokenError(f"Token verification failed: {exc}") from exc

        try:
            return TokenClaims(**payload)
        except Exception as exc:
            raise InvalidTokenError(f"Token claims invalid: {exc}") from exc

    # -------------------------------------------------------------- userinfo

    async def userinfo(self, token: str) -> dict[str, Any]:
        """Call the OIDC ``/userinfo`` endpoint with a Bearer access token."""
        client = self._client()
        resp = await client.get(
            self.userinfo_url,
            headers={"Authorization": f"Bearer {token}"},
        )
        status = getattr(resp, "status_code", 0)
        if status != 200:
            raise InvalidTokenError(
                f"userinfo endpoint returned HTTP {status}"
            )
        return resp.json()

    # ------------------------------------------------------------ introspect

    async def introspect(self, token: str) -> dict[str, Any]:
        """RFC 7662 token introspection (requires client_secret)."""
        if not self.client_secret:
            raise RuntimeError(
                "introspect() requires a configured client_secret"
            )
        client = self._client()
        resp = await client.post(
            self.introspect_url,
            data={"token": token},
            auth=(self.client_id, self.client_secret),
        )
        status = getattr(resp, "status_code", 0)
        if status != 200:
            raise InvalidTokenError(
                f"introspect endpoint returned HTTP {status}"
            )
        return resp.json()
