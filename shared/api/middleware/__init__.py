"""FastAPI middleware for the Spine Hub REST API (V3, Wave 3 Squad C).

Two pieces:

* :mod:`shared.api.middleware.oidc` — cookie/session OIDC layer for the Hub
  SPA (browser flow). Bearer-token verification for API callers is handled
  separately by ``shared.identity.current_user`` in
  ``shared/api/dependencies.py``.
* :mod:`shared.api.middleware.feature_flag` — license-tier feature-gate
  decorator per design decision #23. Disabled flags return ``402 Payment
  Required`` with the upgrade path so the UI can show "upgrade to unlock"
  instead of a 404 / 403.

Both modules are written to be import-safe even when FastAPI / Starlette is
not installed (the type guards mirror the shape used in
``shared/identity/middleware.py``) so ``py_compile`` works in stripped
build environments.
"""

from __future__ import annotations

from shared.api.middleware.feature_flag import (
    FeatureDisabledError,
    feature_flag_dependency,
    is_feature_enabled,
    require_feature_flag,
)
from shared.api.middleware.oidc import (
    SESSION_COOKIE_NAME,
    OidcCookieMiddleware,
    OidcSessionConfig,
    build_login_redirect_url,
    install_oidc_routes,
)

__all__ = [
    # OIDC cookie/session
    "OidcCookieMiddleware",
    "OidcSessionConfig",
    "SESSION_COOKIE_NAME",
    "build_login_redirect_url",
    "install_oidc_routes",
    # Feature-flag
    "FeatureDisabledError",
    "require_feature_flag",
    "feature_flag_dependency",
    "is_feature_enabled",
]
