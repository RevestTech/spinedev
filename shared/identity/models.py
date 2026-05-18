"""
shared/identity/models.py
=========================

Pydantic models for OIDC-derived identity inside Spine.

``TokenClaims`` is a faithful (but liberal) projection of the Keycloak
access-token JWT payload. ``User`` is the higher-level Spine-facing view that
the rest of the codebase consumes — it flattens Keycloak's nested
``realm_access`` / ``resource_access`` / ``groups`` / ``scope`` shapes into
plain lists that are easy to reason about.

``Role`` and ``Group`` are thin value objects; they exist so policy code in
``shared/identity/rbac.py`` and bundle-policy lookups can pass typed objects
around instead of raw strings.

Design notes:

* The Keycloak JWT shape is *partly* standardized (RFC 7519) and *partly*
  Keycloak-specific (``realm_access.roles`` / ``resource_access.<client>``).
  We keep both via ``TokenClaims`` so policy code can introspect either tier.
* ``User.raw_claims`` is preserved so audit / debug paths can see exactly
  what Keycloak said, even after we flatten it.
* Everything is ``BaseModel`` (not ``dataclass``) so it serializes cleanly
  out of FastAPI endpoints and into audit records.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Value objects (roles + groups)
# ---------------------------------------------------------------------------


class Role(BaseModel):
    """Named role — either realm-level or per-client (``client_id``)."""

    name: str
    client_id: str | None = None  # None → realm role
    source: str = "keycloak"

    @property
    def qualified(self) -> str:
        """Return ``client.role`` when scoped to a client, else just ``role``."""
        return f"{self.client_id}.{self.name}" if self.client_id else self.name


class Group(BaseModel):
    """Keycloak group; ``path`` is the canonical Keycloak group path."""

    name: str
    path: str | None = None  # e.g. "/engineering/backend"

    @property
    def qualified(self) -> str:
        """Return the canonical Keycloak group path (or just name)."""
        return self.path or f"/{self.name}"


# ---------------------------------------------------------------------------
# Raw OIDC token claims
# ---------------------------------------------------------------------------


class TokenClaims(BaseModel):
    """JWT access-token claims as returned by Keycloak.

    Field set is deliberately permissive — Keycloak deployments add custom
    claim mappers (e.g. ``tenant_id``, ``department``) that bundle policy may
    rely on; ``extra`` captures anything we don't model explicitly so policy
    code can read it without a model bump.
    """

    model_config = ConfigDict(extra="allow")

    sub: str
    email: str | None = None
    email_verified: bool | None = None
    name: str | None = None
    preferred_username: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    realm_access: dict[str, Any] = Field(default_factory=dict)
    resource_access: dict[str, Any] = Field(default_factory=dict)
    groups: list[str] = Field(default_factory=list)
    scope: str = ""
    azp: str | None = None  # authorized party (client_id token was issued to)
    aud: str | list[str] | None = None
    iss: str | None = None
    exp: int
    iat: int
    jti: str | None = None


# ---------------------------------------------------------------------------
# Spine-facing user view
# ---------------------------------------------------------------------------


class User(BaseModel):
    """Spine-facing representation of an authenticated end-user.

    ``id`` is the Keycloak ``sub`` claim (a UUID). It is the only stable
    identifier — ``email`` / ``username`` may change over time.
    """

    id: str
    email: str | None = None
    username: str | None = None
    name: str | None = None
    roles: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    raw_claims: TokenClaims

    @classmethod
    def from_claims(cls, claims: TokenClaims) -> "User":
        """Build a flattened ``User`` from raw Keycloak token claims."""
        realm_roles = list(claims.realm_access.get("roles", []) or [])
        client_roles: list[str] = []
        for client_id, access in (claims.resource_access or {}).items():
            for role in (access or {}).get("roles", []) or []:
                client_roles.append(f"{client_id}.{role}")

        # De-duplicate while preserving order
        seen: set[str] = set()
        merged_roles: list[str] = []
        for r in realm_roles + client_roles:
            if r not in seen:
                seen.add(r)
                merged_roles.append(r)

        scopes = [s for s in (claims.scope or "").split() if s]

        return cls(
            id=claims.sub,
            email=claims.email,
            username=claims.preferred_username,
            name=claims.name,
            roles=merged_roles,
            groups=list(claims.groups or []),
            scopes=scopes,
            raw_claims=claims,
        )
