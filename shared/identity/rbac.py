"""
shared/identity/rbac.py
=======================

Role-Based Access Control helpers + FastAPI dependencies.

Two layers:

1. **Pure predicates** — ``has_role`` / ``has_scope`` / ``has_any_role`` /
   ``has_group``. Take a ``User`` + a string, return ``bool``. Used by
   business code that needs an inline check.

2. **FastAPI dependency factories** — ``require_role(role)`` /
   ``require_scope(scope)``. Return an ``async`` callable suitable for
   ``Depends(...)`` that wraps ``current_user`` and 403s if the predicate
   fails.

Bundle-policy lookups live in ``BundlePolicyResolver``: a small indirection
so Wave 1+ can plug in a bundle-backed implementation without rewriting
call sites. By default we use the static-claim resolver (roles come from
Keycloak claims). Bundle-driven role expansion (e.g. "this group inherits
these roles per bundle policy") is wired in Wave 2.

Per #8 (hybrid authority): role checks here are the *default* path. The
"bounded emergency override" mechanism is a separate concern owned by the
audit/approval subsystem — not by RBAC predicates.
"""

from __future__ import annotations

from typing import Awaitable, Callable

try:  # pragma: no cover - guarded so py_compile works without fastapi
    from fastapi import Depends, HTTPException, status
except Exception:  # pragma: no cover

    def Depends(dep: Callable[..., object]) -> Callable[..., object]:  # type: ignore[misc]
        """Pass-through shim used only when FastAPI is unavailable."""
        return dep

    class HTTPException(Exception):  # type: ignore[no-redef]
        """Minimal HTTPException stand-in so the module loads everywhere."""

        def __init__(
            self,
            status_code: int,
            detail: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> None:
            super().__init__(detail or "")
            self.status_code = status_code
            self.detail = detail
            self.headers = headers

    class _StatusShim:  # noqa: D401
        """Minimal subset of starlette.status."""

        HTTP_401_UNAUTHORIZED = 401
        HTTP_403_FORBIDDEN = 403

    status = _StatusShim()  # type: ignore[assignment]


from .middleware import current_user
from .models import User


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AuthorizationError(HTTPException):
    """403 Forbidden — convenience wrapper around HTTPException."""

    def __init__(self, detail: str = "Forbidden") -> None:
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


# ---------------------------------------------------------------------------
# Bundle-policy resolver
# ---------------------------------------------------------------------------


class BundlePolicyResolver:
    """Resolve effective roles/scopes for a ``User`` against bundle policy.

    The default implementation is a pass-through — effective roles == raw
    claims. Wave 2 will swap in a bundle-driven resolver that expands group
    membership into roles per bundle policy (e.g. "members of
    ``/engineering/backend`` get role ``deploy:prod``").

    Single-process singleton via module-level ``_RESOLVER``; overridable by
    ``set_policy_resolver()`` for tests or alternate implementations.
    """

    def effective_roles(self, user: User) -> set[str]:
        """Return the union of claim-roles + bundle-expanded roles."""
        return set(user.roles)

    def effective_scopes(self, user: User) -> set[str]:
        """Return the union of claim-scopes + bundle-expanded scopes."""
        return set(user.scopes)


_RESOLVER: BundlePolicyResolver = BundlePolicyResolver()


def set_policy_resolver(resolver: BundlePolicyResolver) -> None:
    """Install a non-default ``BundlePolicyResolver``."""
    global _RESOLVER
    _RESOLVER = resolver


def get_policy_resolver() -> BundlePolicyResolver:
    """Return the active ``BundlePolicyResolver``."""
    return _RESOLVER


# ---------------------------------------------------------------------------
# Pure predicates
# ---------------------------------------------------------------------------


def has_role(user: User, role: str) -> bool:
    """True if ``user`` has ``role`` (after bundle-policy expansion)."""
    return role in _RESOLVER.effective_roles(user)


def has_any_role(user: User, roles: list[str] | tuple[str, ...]) -> bool:
    """True if ``user`` has at least one of ``roles``."""
    effective = _RESOLVER.effective_roles(user)
    return any(r in effective for r in roles)


def has_scope(user: User, scope: str) -> bool:
    """True if the access token included ``scope``."""
    return scope in _RESOLVER.effective_scopes(user)


def has_group(user: User, group: str) -> bool:
    """True if ``group`` (Keycloak path or name) appears in user's groups."""
    return group in user.groups


# ---------------------------------------------------------------------------
# FastAPI dependency factories
# ---------------------------------------------------------------------------


def require_role(role: str) -> Callable[..., Awaitable[User]]:
    """Return a FastAPI dependency that 403s unless ``user`` has ``role``.

    Usage::

        @router.get("/admin", dependencies=[Depends(require_role("admin"))])
        async def admin_only(): ...
    """

    async def _dep(user: User = Depends(current_user)) -> User:
        if not has_role(user, role):
            raise AuthorizationError(f"Requires role: {role}")
        return user

    _dep.__name__ = f"require_role_{role}"
    return _dep


def require_any_role(*roles: str) -> Callable[..., Awaitable[User]]:
    """403 unless user has any of ``roles`` (logical OR)."""

    async def _dep(user: User = Depends(current_user)) -> User:
        if not has_any_role(user, list(roles)):
            raise AuthorizationError(
                f"Requires one of: {', '.join(roles)}"
            )
        return user

    _dep.__name__ = f"require_any_role_{'_'.join(roles)}"
    return _dep


def require_scope(scope: str) -> Callable[..., Awaitable[User]]:
    """Return a FastAPI dependency that 403s unless token contains ``scope``."""

    async def _dep(user: User = Depends(current_user)) -> User:
        if not has_scope(user, scope):
            raise AuthorizationError(f"Requires scope: {scope}")
        return user

    _dep.__name__ = f"require_scope_{scope}"
    return _dep


def require_group(group: str) -> Callable[..., Awaitable[User]]:
    """403 unless user belongs to Keycloak ``group`` (path or name)."""

    async def _dep(user: User = Depends(current_user)) -> User:
        if not has_group(user, group):
            raise AuthorizationError(f"Requires group: {group}")
        return user

    _dep.__name__ = f"require_group_{group.replace('/', '_')}"
    return _dep
