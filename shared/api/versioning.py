"""Spine REST API versioning policy + helpers (V3 Wave 6 Stream J, #30).

The public Hub REST surface is **versioned via URL prefix**. The whole
``shared.api.routes`` package agrees on one of three namespaces:

* ``/api/v1`` — **historical / deprecated.** Pre-V3 callers (the v2
  Bash-era CLI shipped a Hub stub on ``/api/v1``). For backward compat we
  expose :func:`redirect_v1_to_v2_middleware` which rewrites any incoming
  ``/api/v1/<path>`` into ``/api/v2/<path>`` with a ``307`` redirect that
  preserves the method + body. Cut date: 2027-Q1 (v1.2).
* ``/api/v2`` — **current public.** Every Wave 3 route mounts under this
  prefix. New endpoints SHOULD land here unless they introduce a breaking
  change. (Backwards-compatible additions never bump the version — that
  is the whole point of additive evolution.)
* ``/api/v3`` — **reserved.** Cut for the *first* breaking change after
  GA, then run v2 + v3 in parallel for at least one minor (the dual-run
  window). Until then no routes mount here; the constants exist so a
  forgetful future PR doesn't reinvent the wheel with a typo.

Why "v2 = current public" and not "v1 = current public"? Because the
substrate (orchestrator, MCP, dependencies) had already shipped under
``/api/v2`` in V2 → renaming the live prefix would have broken every
running Hub on the day of the v3 cutover. We absorbed the cost of an
off-by-one version label rather than the cost of an in-flight rename.
See ``docs/V3_DESIGN_DECISIONS.md`` #30 for the full rationale.

Public surface (callers should ONLY import from this module — the bare
strings ``/api/v1`` etc. are an anti-pattern):

    API_V1_PREFIX, API_V2_PREFIX, API_V3_PREFIX
    CURRENT_PUBLIC_PREFIX                  (= API_V2_PREFIX)
    SUPPORTED_PREFIXES                     (the parallel-run set)
    versioned_prefix(version, resource)    helper for new routes
    redirect_v1_to_v2_middleware(app)      ASGI wiring helper
    V1_TO_V2_REDIRECT_STATUS               (307)
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Final, Literal

try:  # pragma: no cover - guarded for py_compile
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import RedirectResponse
    from starlette.types import ASGIApp
except Exception:  # pragma: no cover

    class BaseHTTPMiddleware:  # type: ignore[no-redef]
        """Stand-in BaseHTTPMiddleware for stripped envs."""

        def __init__(self, app: object) -> None:
            self.app = app

    Request = object  # type: ignore[assignment,misc]
    RedirectResponse = object  # type: ignore[assignment,misc]
    ASGIApp = object  # type: ignore[assignment,misc]


logger = logging.getLogger("spine.api.versioning")


# ---------------------------------------------------------------------------
# Constants — single source of truth for prefix strings
# ---------------------------------------------------------------------------

#: Historical / deprecated namespace. Subject to redirect middleware.
API_V1_PREFIX: Final[str] = "/api/v1"

#: Current public API namespace (post-V3). All Wave 3+ routes mount here.
API_V2_PREFIX: Final[str] = "/api/v2"

#: Reserved for the first breaking change post-GA. No routes mount here yet.
API_V3_PREFIX: Final[str] = "/api/v3"

#: Alias the rest of the codebase should import when it just wants
#: "the current public prefix" — minimises churn when a future version
#: rotates the default.
CURRENT_PUBLIC_PREFIX: Final[str] = API_V2_PREFIX

#: Versions actively served by this build. v3 gets added to this tuple on
#: the cutover commit, not before.
SUPPORTED_PREFIXES: Final[tuple[str, ...]] = (API_V2_PREFIX,)

#: HTTP status used by the v1 -> v2 redirect. 307 (Temporary Redirect)
#: preserves the request method + body, which 301/302 do NOT for POST/PATCH
#: in most clients. Use 308 only if you also want to lock the client into
#: caching the redirect — we deliberately do NOT, because the v2 path may
#: itself migrate to v3 eventually.
V1_TO_V2_REDIRECT_STATUS: Final[int] = 307

ApiVersion = Literal["v1", "v2", "v3"]
"""Type alias for callers that prefer the short label over the prefix string."""


_VERSION_TO_PREFIX: Final[dict[str, str]] = {
    "v1": API_V1_PREFIX,
    "v2": API_V2_PREFIX,
    "v3": API_V3_PREFIX,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def versioned_prefix(version: ApiVersion, resource: str) -> str:
    """Build a versioned route prefix.

    >>> versioned_prefix("v2", "integrations")
    '/api/v2/integrations'
    >>> versioned_prefix("v3", "/integrations")
    '/api/v3/integrations'

    Centralising the join means a single point of validation (we reject
    unknown versions eagerly so a typo at route-construction time fails
    loudly instead of mounting at a silently-wrong path) AND a single
    leading-slash policy (always exactly one ``/``).

    Args:
        version: One of ``"v1" | "v2" | "v3"``. Anything else raises
            ``ValueError``.
        resource: Resource path segment, with or without a leading slash.
            Empty string returns the bare version prefix.

    Returns:
        Joined path string (no trailing slash).
    """
    if version not in _VERSION_TO_PREFIX:
        raise ValueError(
            f"Unknown API version {version!r}; expected one of "
            f"{sorted(_VERSION_TO_PREFIX)}",
        )
    prefix = _VERSION_TO_PREFIX[version]
    if not resource:
        return prefix
    cleaned = resource if resource.startswith("/") else f"/{resource}"
    # Strip trailing slash for canonical form — FastAPI does the right
    # thing either way but the audit log + dashboards prefer the bare path.
    return f"{prefix}{cleaned}".rstrip("/") or prefix


def is_supported_version(prefix_or_version: str) -> bool:
    """True if the given prefix/short-label is currently served by this Hub.

    Accepts either ``"v2"`` or ``"/api/v2"`` for convenience; the v1
    namespace is *not* "supported" (it only redirects), which is why
    callers should use this helper instead of comparing against
    :data:`SUPPORTED_PREFIXES` directly.
    """
    if not prefix_or_version:
        return False
    normalised = (
        _VERSION_TO_PREFIX.get(prefix_or_version)
        if prefix_or_version in _VERSION_TO_PREFIX
        else prefix_or_version
    )
    return normalised in SUPPORTED_PREFIXES


# ---------------------------------------------------------------------------
# v1 -> v2 redirect middleware
# ---------------------------------------------------------------------------


class RedirectV1ToV2Middleware(BaseHTTPMiddleware):
    """Issue a 307 from ``/api/v1/<x>`` to ``/api/v2/<x>``.

    Why a middleware and not a FastAPI route prefix? Because we want EVERY
    v1 path — including paths that have no v2 equivalent — to redirect
    with the same status, so the SPA + downstream clients can detect the
    deprecation uniformly. A FastAPI router with ``include_router(...,
    prefix="/api/v1")`` would 404 on paths not exposed by v2; the
    middleware instead lets v2's own 404 handler answer (after the
    redirect), preserving the v2 error envelope contract.

    The middleware sets ``Deprecation`` and ``Sunset`` headers per
    [RFC 8594] so well-behaved clients log the deprecation centrally.
    Sunset is configured at 2027-01-01 (v1.2 cut date).
    """

    #: RFC 8594 sunset header value. Bump when the cut date changes.
    SUNSET_HEADER: Final[str] = "Fri, 01 Jan 2027 00:00:00 GMT"

    async def dispatch(
        self,
        request: "Request",
        call_next: Callable[["Request"], Awaitable[object]],
    ) -> object:  # type: ignore[override]
        path = request.url.path
        if not path.startswith(API_V1_PREFIX + "/") and path != API_V1_PREFIX:
            return await call_next(request)

        # Rewrite ONLY the version segment; preserve query string verbatim
        # (clients may rely on ordering for signed-URL schemes).
        suffix = path[len(API_V1_PREFIX):] or "/"
        new_path = f"{API_V2_PREFIX}{suffix}"
        target = new_path
        qs = request.url.query
        if qs:
            target = f"{new_path}?{qs}"

        logger.info(
            "api_v1_redirect",
            extra={
                "from_path": path,
                "to_path": new_path,
                "method": request.method,
                "deprecation_sunset": self.SUNSET_HEADER,
            },
        )
        response = RedirectResponse(
            url=target,
            status_code=V1_TO_V2_REDIRECT_STATUS,
        )
        # Per RFC 8594: signal deprecation + the planned removal date.
        response.headers["Deprecation"] = "true"
        response.headers["Sunset"] = self.SUNSET_HEADER
        response.headers["Link"] = (
            f'<{API_V2_PREFIX}>; rel="successor-version"'
        )
        return response


def redirect_v1_to_v2_middleware(app: "ASGIApp") -> "ASGIApp":
    """Install :class:`RedirectV1ToV2Middleware` on a FastAPI/Starlette app.

    Idiom matches FastAPI's ``app.add_middleware`` so callers can do::

        from shared.api.versioning import redirect_v1_to_v2_middleware

        app = FastAPI(...)
        redirect_v1_to_v2_middleware(app)

    Returns the same app object so the call chains nicely.
    """
    # Lazy import — FastAPI's add_middleware is on Starlette.applications,
    # the same hierarchy our other middlewares hook into.
    try:
        app.add_middleware(RedirectV1ToV2Middleware)  # type: ignore[attr-defined]
    except AttributeError:  # pragma: no cover — non-FastAPI ASGI app
        raise RuntimeError(
            "redirect_v1_to_v2_middleware requires a FastAPI/Starlette app "
            "with .add_middleware(); got "
            f"{type(app).__name__}"
        )
    return app


__all__ = [
    "API_V1_PREFIX",
    "API_V2_PREFIX",
    "API_V3_PREFIX",
    "CURRENT_PUBLIC_PREFIX",
    "SUPPORTED_PREFIXES",
    "V1_TO_V2_REDIRECT_STATUS",
    "ApiVersion",
    "RedirectV1ToV2Middleware",
    "is_supported_version",
    "redirect_v1_to_v2_middleware",
    "versioned_prefix",
]
