"""Feature-flag enforcement middleware (#23 — Day-1 licensing primitive).

Usage::

    from shared.api.middleware.feature_flag import require_feature_flag

    @router.get(
        "/federation/hubs",
        dependencies=[Depends(require_feature_flag("federation"))],
    )
    async def list_hubs(): ...

When the flag is disabled the route returns ``402 Payment Required`` with
an ``upgrade_path`` field pointing the SPA at the in-product upgrade
page. We use 402 (rather than 403/404) so the SPA can render the
"upgrade to unlock" UI without ambiguity — disabled-but-known is a
different state from forbidden or missing.

Wave 4 ships ``shared/license/`` with the signed-bundle evaluator. Until
then this module exposes ``is_enabled(flag)`` returning ``True`` for all
known flags — the *contract* is in place so route code doesn't have to
change when the evaluator lands.

Per #23 the universe of flags is open-ended; we list the *currently
referenced* flags so a typo at a call site is caught at startup, not at
the first request. New routes that need a new flag must add it here.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

try:  # pragma: no cover - guarded for py_compile
    from fastapi import Depends, HTTPException
except Exception:  # pragma: no cover

    def Depends(dep: Callable[..., object]) -> Callable[..., object]:  # type: ignore[misc]
        return dep

    class HTTPException(Exception):  # type: ignore[no-redef]
        """Stand-in HTTPException for py_compile in stripped envs."""

        def __init__(self, status_code: int, detail: object = None) -> None:
            super().__init__(str(detail))
            self.status_code = status_code
            self.detail = detail


logger = logging.getLogger("spine.api.feature_flag")

#: 402 Payment Required — the right HTTP status for "you don't have this
#: feature on your current license tier; here is the upgrade path." Most
#: HTTP clients treat 402 as a soft error, exactly what the SPA wants.
HTTP_402_PAYMENT_REQUIRED = 402

#: Canonical set of feature flags this codebase references. Wave 4's
#: license evaluator will replace the in-memory stub with a signed-bundle
#: lookup; the flag NAMES (not their values) are the stable contract.
KNOWN_FEATURE_FLAGS: frozenset[str] = frozenset(
    {
        # Hub / federation
        "federation",
        "hub_admin",
        "remote_mcp",
        # Identity / SSO
        "sso_oidc",
        "sso_scim",
        # Channels (per #6)
        "channel_slack",
        "channel_pagerduty",
        "channel_sms",
        "channel_whatsapp",
        "channel_teams",
        # Integrations (per #3 + #24)
        "integration_github",
        "integration_linear",
        "integration_jira",
        "integration_vanta",
        "integration_drata",
        # Roles (per #19)
        "role_devops",
        "role_customer_support",
        "role_compliance_officer",
        "role_security_engineer",
        "role_tech_writer",
        "role_release_manager",
        # Quotas
        "quota_max_projects",
        "quota_max_concurrent_runs",
        # Licensing internals (always-on; gates the upgrade UI itself)
        "license_inspector",
    }
)


# ---------------------------------------------------------------------------
# Wave-3 stub evaluator — replaced by shared/license/ in Wave 4
# ---------------------------------------------------------------------------


def is_feature_enabled(flag: str) -> bool:
    """Return True if ``flag`` is enabled on the current license bundle.

    Wave 4 (Squad B) wired the real signed-bundle evaluator at
    :func:`license.feature_flags.is_enabled`. The contract is identical to
    the Wave 3 stub: unknown flags raise ``KeyError`` so a typo at the
    call site (e.g. ``require_feature_flag("federtion")``) fails at the
    first request rather than silently returning True.

    Fail-open semantics during the bootstrap window (Hub still starting
    up, no ``ActiveBundle`` installed yet) are preserved by catching the
    one specific case where the licence subsystem is unreachable. Every
    other call path delegates straight to the licence evaluator.
    """
    if flag not in KNOWN_FEATURE_FLAGS:
        raise KeyError(
            f"Unknown feature flag {flag!r}; add it to "
            "shared.api.middleware.feature_flag.KNOWN_FEATURE_FLAGS"
        )
    try:
        from license.bundle_verifier import get_active_bundle  # noqa: PLC0415
        from license.feature_flags import is_enabled  # noqa: PLC0415
    except Exception:  # noqa: BLE001 — license subsystem missing: fail-open
        return True
    # Bootstrap window: Hub started up, license subsystem importable, but no
    # signed bundle has been loaded yet. Per the Wave-3 contract preserved
    # here, we fail OPEN until startup completes so health checks + the
    # initial admin login can reach their endpoints. Once a bundle is
    # installed, the evaluator is the single source of truth.
    if get_active_bundle() is None:
        return True
    try:
        return bool(is_enabled(flag))
    except KeyError:
        raise
    except Exception:  # noqa: BLE001 — evaluator hiccup: fail-open, log later
        return True


# ---------------------------------------------------------------------------
# Errors + dependency factory
# ---------------------------------------------------------------------------


class FeatureDisabledError(HTTPException):
    """402 Payment Required wrapper with structured upgrade-path body."""

    def __init__(self, flag: str) -> None:
        super().__init__(
            status_code=HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error_code": "feature_disabled",
                "message": f"Feature {flag!r} is not enabled on this license.",
                "feature_flag": flag,
                "upgrade_path": "/hub/settings/license",
            },
        )


def require_feature_flag(flag: str) -> Callable[..., Awaitable[None]]:
    """FastAPI dependency factory that 402s if ``flag`` is disabled.

    Returns an ``async`` callable so it composes naturally inside
    ``dependencies=[Depends(...)]`` lists alongside ``current_user``.
    """
    # Validate the flag name eagerly so a typo at registration time
    # raises during route construction, not at the first request.
    if flag not in KNOWN_FEATURE_FLAGS:
        raise KeyError(
            f"Unknown feature flag {flag!r}; add it to "
            "shared.api.middleware.feature_flag.KNOWN_FEATURE_FLAGS"
        )

    async def _dep() -> None:
        if not is_feature_enabled(flag):
            logger.info("feature_flag_blocked", extra={"flag": flag})
            raise FeatureDisabledError(flag)

    _dep.__name__ = f"require_feature_flag_{flag}"
    return _dep


def feature_flag_dependency(flag: str):
    """Convenience wrapper: ``Depends(...)`` around ``require_feature_flag(flag)``."""
    return Depends(require_feature_flag(flag))


__all__ = [
    "KNOWN_FEATURE_FLAGS",
    "HTTP_402_PAYMENT_REQUIRED",
    "FeatureDisabledError",
    "is_feature_enabled",
    "require_feature_flag",
    "feature_flag_dependency",
]
