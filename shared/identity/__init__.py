"""
shared/identity — Keycloak-backed OIDC identity for Spine v3.

Per Spine v3 design decision #25 (Identity = Keycloak embedded by default),
Spine Hub never directly handles SAML / SCIM / social-login / MFA logic.
Customer IdPs (Okta / Azure AD / Google Workspace / Ping / OneLogin) federate
into Keycloak as brokered upstream IdPs; Spine Hub trusts only Keycloak.

This package is the OIDC client library that every Wave 1+ feature uses to
obtain a ``current_user``. It is intentionally a *library* — Wave 3 wires it
into the FastAPI app by replacing the header-stub in
``shared/api/dependencies.py`` with the ``current_user`` dependency exported
here.

Hard constraints (locked in by design):

* Wave 0 supports Bearer JWT verification only. Cookie / session support is
  a Wave 3 concern.
* Signature verification uses RS256 against the Keycloak realm JWKS endpoint;
  JWKS is cached for ``DEFAULT_JWKS_TTL_SECONDS`` (5 min default).
* No password grant flow — ever. Authorization-code via the Keycloak login
  page is the only end-user flow we expose.
* Feature-flag lightening (#14) maps the customer's licensed tier to which
  Keycloak capabilities are surfaced in the Hub UI.

Public API:

    from shared.identity import (
        KeycloakClient,
        current_user, optional_user,
        require_role, require_scope, has_role, has_scope,
        User, Role, Group, TokenClaims,
    )
"""

from __future__ import annotations

from .keycloak_client import (
    DEFAULT_JWKS_TTL_SECONDS,
    InvalidTokenError,
    JWKSFetchError,
    KeycloakClient,
)
from .middleware import (
    AuthenticationError,
    bearer_token_from_header,
    current_user,
    get_keycloak_client,
    optional_user,
    set_keycloak_client,
)
from .models import Group, Role, TokenClaims, User
from .rbac import (
    AuthorizationError,
    has_role,
    has_scope,
    require_role,
    require_scope,
)

__all__ = [
    # Models
    "User",
    "Role",
    "Group",
    "TokenClaims",
    # Keycloak OIDC client
    "KeycloakClient",
    "DEFAULT_JWKS_TTL_SECONDS",
    "JWKSFetchError",
    "InvalidTokenError",
    # FastAPI dependencies
    "current_user",
    "optional_user",
    "bearer_token_from_header",
    "get_keycloak_client",
    "set_keycloak_client",
    "AuthenticationError",
    # RBAC
    "require_role",
    "require_scope",
    "has_role",
    "has_scope",
    "AuthorizationError",
]
