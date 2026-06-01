"""FastAPI dependencies — asyncpg pool, MCP client, OIDC ``current_user``.

REBUILD (V3, Wave 3 Squad C) of the original STORY-9.9.2 stub. The Wave 0/1
substrate (``shared.identity``, ``shared.secrets``, ``shared.mcp``) is now
in place, so the three placeholders that the v3 triage flagged as ``REBUILD``
on ``shared/api/dependencies.py`` are addressed here:

1. **Auth (#25)** — the header-stub ``current_user`` (``X-Spine-Actor``) is
   replaced by ``shared.identity.current_user`` (Bearer JWT verified against
   Keycloak's JWKS). Cookie/session is a separate concern owned by
   ``shared.api.middleware.oidc`` — Bearer is the API contract here.

2. **DB (#30 heavier API + #9 vault-only secrets)** — the subprocess ``psql``
   handle is replaced by an ``asyncpg`` connection pool. The DSN is fetched
   from ``shared.secrets.get_secret('spine/postgres/dsn')`` at Hub startup;
   we never read DSN from env vars (per design decision #9). The pool is
   sized ``min=2 max=20`` — small enough to share a free-tier Postgres,
   large enough to serve a Hub's hot path without blocking the event loop.
   The legacy ``DbHandle`` shim around ``psql`` is preserved as a thin
   wrapper over the pool so the v2 routes (``approvals.py`` / ``audit.py``
   / ``projects.py``) keep working without a coordinated rewrite — they
   call ``await pool.fetch(sql)``, which now routes to asyncpg and returns
   ``[{"_row": <text>}]`` to match the historical contract.

3. **MCP (#4 federation)** — ``mcp_client()`` still returns the in-process
   dispatcher for Hub-owned tools, but the indirection layer now supports
   *both* in-process AND remote-MCP transport. ``set_mcp_transport("remote",
   url=..., role=...)`` records the federation parent's MCP URL +
   federation role; the FastAPI lifespan in ``shared/api/app.py`` then
   constructs a long-lived :class:`shared.mcp.server_remote.RemoteMcpClient`
   and registers it via :func:`set_remote_mcp_client`. ``mcp_client()``
   returns the in-process client by default; verbs that explicitly
   request the remote transport receive the federation client (used for
   the rare cross-Hub tool delegation case — single-Hub deployments stay
   in-process for free).

New runtime deps (already in ``requirements.txt`` — not modified by this
file, only noted here):
    * ``asyncpg`` (>=0.29) — async Postgres driver
    * ``httpx``  (>=0.27) — already required by ``shared.identity``

Scope boundary: this module owns the *dependencies* — wiring (lifespan,
pool open/close, vault fetch) lives in ``shared/api/app.py``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal, Optional

try:  # pragma: no cover - optional at py_compile time
    import asyncpg  # type: ignore
except Exception:  # pragma: no cover
    asyncpg = None  # type: ignore[assignment]

# Re-export ``current_user`` from the OIDC layer so route modules import a
# single name from a single place (``from shared.api.dependencies import
# current_user``). Aliases preserve the public surface that Wave 2 routes
# already import.
from shared.identity import current_user as _oidc_current_user  # noqa: F401
from shared.identity import optional_user as _oidc_optional_user  # noqa: F401
from shared.identity.models import User

logger = logging.getLogger("spine.api.deps")

# Hub main asyncio loop — set in ``app.lifespan`` so sync MCP runners invoked
# via ``asyncio.to_thread`` can schedule coroutines that use the asyncpg pool.
_hub_event_loop: asyncio.AbstractEventLoop | None = None


def set_hub_event_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    """Record the FastAPI lifespan loop (or clear on shutdown)."""
    global _hub_event_loop
    _hub_event_loop = loop


def get_hub_event_loop() -> asyncio.AbstractEventLoop | None:
    return _hub_event_loop


# ---------------------------------------------------------------------------
# Public surface — preserves the names the v2 routes already import
# ---------------------------------------------------------------------------

# OIDC dependencies — `current_user` is the Bearer-verified ``User`` from
# Keycloak. Cookie-session for the Hub SPA is layered ON TOP of this in
# ``shared.api.middleware.oidc`` (which mints a Bearer-equivalent claim
# from a session cookie before this dependency runs).
current_user = _oidc_current_user
optional_user = _oidc_optional_user

#: Vault path the Hub uses for its Postgres DSN. Per #9 we *never* read the
#: DSN VALUE from an env var; the env var is only allowed as the vault
#: PATH override, which is metadata, not a secret.
DSN_VAULT_PATH = os.environ.get(
    "SPINE_DB_DSN_VAULT_PATH", "spine/postgres/dsn"
)

#: Pool sizing — small floor, modest ceiling. The Hub is mostly an
#: orchestration surface; long-running analytic queries are pushed to
#: ``shared/memory/`` (per Wave 2). The pool is shared across all routes.
DEFAULT_POOL_MIN_SIZE = 2
DEFAULT_POOL_MAX_SIZE = 20
DEFAULT_POOL_COMMAND_TIMEOUT_SECS = 15.0


# ---------------------------------------------------------------------------
# asyncpg connection pool — replaces subprocess psql
# ---------------------------------------------------------------------------


class DbPoolNotInitialized(RuntimeError):
    """Raised when a route depends on the pool before lifespan ran ``init_db_pool``."""


@dataclass
class DbHandle:
    """Thin shim that exposes the legacy ``await db.fetch(sql)`` shape.

    Existing v2 routes (``approvals.py`` / ``audit.py``) built their SQL
    string and expected ``[{"_row": "<text>"}]`` back — a single-text-column
    contract because v1 used ``psql -At``. We preserve that contract here
    so the rewrite is incremental: routes can be migrated to native
    asyncpg row dicts one at a time without breaking the rest.

    The wrapper holds a *reference* to the asyncpg pool (not the pool
    itself) so swapping the pool (e.g. for a test mock) reaches every
    DbHandle in flight.
    """

    pool_ref: "_PoolRef"

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        """Run a query; return one ``{"_row": "<text>"}`` per output row.

        Mirrors the legacy ``psql -At`` shape. We coerce every column on
        every row into a tab-joined string to keep the contract identical
        for the v2 routes — they build ``json_build_object(...)::text``
        themselves and expect a single text column out.
        """
        pool = self.pool_ref.require()
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
        out: list[dict[str, Any]] = []
        for r in rows:
            # Single-column SELECT → preserve historical contract: ``_row``
            # is the rendered text. Multi-column SELECT (rare in v2) →
            # join with tabs, also matching ``psql -At -F<tab>`` output.
            values = list(r.values()) if hasattr(r, "values") else list(r)
            if len(values) == 1:
                out.append({"_row": "" if values[0] is None else str(values[0])})
            else:
                out.append({"_row": "\t".join("" if v is None else str(v) for v in values)})
        return out

    async def fetch_rows(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        """Native asyncpg row-dict variant — new routes prefer this."""
        pool = self.pool_ref.require()
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
        return [dict(r) for r in rows]

    async def execute(self, sql: str, *args: Any) -> str:
        """Execute a non-result statement; returns the asyncpg command tag."""
        pool = self.pool_ref.require()
        async with pool.acquire() as conn:
            return await conn.execute(sql, *args)

    async def ping(self) -> bool:
        """Return True when ``SELECT 1`` succeeds."""
        try:
            pool = self.pool_ref.require()
        except DbPoolNotInitialized:
            return False
        try:
            async with pool.acquire() as conn:
                val = await conn.fetchval("SELECT 1;")
                return val == 1
        except Exception:  # noqa: BLE001
            return False


@dataclass
class _PoolRef:
    """Holder so callers can keep a stable handle while the pool is rotated.

    During tests we want to swap the pool in/out without rebuilding every
    ``DbHandle`` instance the FastAPI dependency graph already produced.
    A small indirection layer (this class) lets us do that.
    """

    pool: Any | None = None

    def require(self) -> Any:
        """Return the pool or raise ``DbPoolNotInitialized``."""
        if self.pool is None:
            raise DbPoolNotInitialized(
                "asyncpg pool is not initialized; call init_db_pool() in "
                "the FastAPI lifespan first"
            )
        return self.pool


_POOL_REF: _PoolRef = _PoolRef()
_DB_HANDLE: DbHandle = DbHandle(pool_ref=_POOL_REF)
_INIT_LOCK = asyncio.Lock()


async def init_db_pool(
    *,
    dsn: Optional[str] = None,
    min_size: int = DEFAULT_POOL_MIN_SIZE,
    max_size: int = DEFAULT_POOL_MAX_SIZE,
    command_timeout: float = DEFAULT_POOL_COMMAND_TIMEOUT_SECS,
    secret_fetcher: Optional[Callable[[str], Awaitable[str]]] = None,
) -> Any:
    """Idempotently create the asyncpg pool and stash it in ``_POOL_REF``.

    ``dsn`` is allowed as an explicit override (tests inject a sqlite-style
    URL here, or a known DSN); production callers should pass *nothing* and
    let the function fetch from vault.

    ``secret_fetcher`` defaults to ``shared.secrets.get_secret`` so the only
    code path that reads DSN VALUES in production is the vault adapter. Tests
    inject a callable that returns a known string.
    """
    if asyncpg is None:  # pragma: no cover - guarded
        raise RuntimeError(
            "asyncpg is not installed; add `asyncpg` to your runtime env"
        )
    async with _INIT_LOCK:
        if _POOL_REF.pool is not None:
            return _POOL_REF.pool
        if dsn is None:
            if secret_fetcher is None:
                # Lazy import — `shared.secrets` is only optional in some
                # py_compile-only environments.
                from shared.secrets import get_secret  # noqa: PLC0415

                secret_fetcher = get_secret  # type: ignore[assignment]
            dsn = await secret_fetcher(DSN_VAULT_PATH)  # type: ignore[misc]
            if not dsn:
                raise RuntimeError(
                    f"vault returned empty DSN at {DSN_VAULT_PATH!r}; "
                    "configure the Hub Postgres DSN via the install wizard"
                )
        pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=min_size,
            max_size=max_size,
            command_timeout=command_timeout,
        )
        _POOL_REF.pool = pool
        logger.info(
            "asyncpg_pool_ready",
            extra={"min_size": min_size, "max_size": max_size},
        )
        return pool


async def close_db_pool() -> None:
    """Close the asyncpg pool — paired with ``init_db_pool`` in lifespan."""
    if _POOL_REF.pool is None:
        return
    try:
        await _POOL_REF.pool.close()
    finally:
        _POOL_REF.pool = None
        logger.info("asyncpg_pool_closed")


def set_db_pool(pool: Any) -> None:
    """Test/seam helper: swap the pool atomically (e.g. inject a mock)."""
    _POOL_REF.pool = pool


def get_db_pool() -> DbHandle:
    """FastAPI dependency — returns the shared ``DbHandle``.

    Synchronous return type (matches v2) so existing ``Annotated[DbHandle,
    Depends(get_db_pool)]`` parameter signatures keep working.
    """
    return _DB_HANDLE


def get_db_pool_raw() -> Any:
    """Return the raw asyncpg pool — for code that wants ``async with
    pool.acquire()`` directly. Raises ``DbPoolNotInitialized`` if uninit."""
    return _POOL_REF.require()


# ---------------------------------------------------------------------------
# MCP client — in-process + remote-MCP placeholder
# ---------------------------------------------------------------------------


McpTransport = Literal["in_process", "remote"]


@dataclass
class _McpTransportConfig:
    """Selected transport + its parameters (remote URL, federation role, …).

    ``role`` is the LOCAL Hub's federation role from the parent's
    perspective; used by :class:`shared.mcp.server_remote.RemoteMcpClient`
    to compute the vault paths for the mTLS material + bearer
    (``federation/mtls/<role>/...`` and ``federation/bearer/<role>``).
    """

    kind: McpTransport = "in_process"
    remote_url: Optional[str] = None
    remote_role: str = "child"
    remote_actor: str = "federation_child"


_MCP_TRANSPORT: _McpTransportConfig = _McpTransportConfig()

#: Long-lived ``RemoteMcpClient`` instance — populated by the FastAPI
#: lifespan in :mod:`shared.api.app` when the federation bundle declares
#: an upstream parent. ``None`` for single-Hub deployments (the vast
#: majority of installations).
_REMOTE_MCP_CLIENT: Any | None = None


def set_mcp_transport(
    kind: McpTransport,
    *,
    url: Optional[str] = None,
    role: str = "child",
    actor: str = "federation_child",
) -> None:
    """Switch the process-wide MCP transport.

    ``"in_process"`` (default) → ``shared.mcp.tools.TOOL_REGISTRY`` dispatch.
    ``"remote"`` → :class:`shared.mcp.server_remote.RemoteMcpClient`
    against the federation parent at ``url``, with mTLS + bearer
    fetched from vault under the federation ``role``.

    This function only records configuration. The actual ``RemoteMcpClient``
    is constructed by the FastAPI lifespan via
    :func:`shared.mcp.server_remote.RemoteMcpClient.open` so vault IO
    happens once at startup (not on every request) — wired below via
    :func:`set_remote_mcp_client`.
    """
    if kind == "remote" and not url:
        raise ValueError("set_mcp_transport('remote', ...) requires url=...")
    _MCP_TRANSPORT.kind = kind
    _MCP_TRANSPORT.remote_url = url
    _MCP_TRANSPORT.remote_role = role
    _MCP_TRANSPORT.remote_actor = actor


def get_mcp_transport() -> _McpTransportConfig:
    """Inspect the currently-configured MCP transport (for diagnostics)."""
    return _MCP_TRANSPORT


def set_remote_mcp_client(client: Any | None) -> None:
    """Register (or clear) the long-lived remote-MCP client.

    Called by the FastAPI lifespan AFTER ``RemoteMcpClient.open(...)``
    succeeds (so a vault outage or unreachable parent fails the lifespan
    rather than every individual request). Passing ``None`` clears it
    (used on lifespan shutdown).
    """
    global _REMOTE_MCP_CLIENT
    _REMOTE_MCP_CLIENT = client


def get_remote_mcp_client() -> Any | None:
    """Return the registered remote-MCP client, or ``None`` if unconfigured."""
    return _REMOTE_MCP_CLIENT


class McpClient:
    """Dispatcher to the unified MCP tool registry — in-process or remote.

    Same shape as the v2 client so existing routes (``projects.py``) keep
    working. New code calling out to the federation parent should
    ``await mcp.acall(...)`` instead of ``mcp.call(...)`` to avoid the
    sync-over-async bridge.
    """

    def __init__(self, transport: _McpTransportConfig | None = None) -> None:
        self._transport = transport or _MCP_TRANSPORT

    def call(
        self,
        name: str,
        payload: dict[str, Any],
        *,
        feature_flag_required: Optional[str] = None,
        actor_token_claims: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Validate payload, invoke the tool, return its data dict."""
        if self._transport.kind == "remote":
            remote = _REMOTE_MCP_CLIENT
            if remote is None:
                # Configuration says remote, lifespan never registered a
                # client. Fail closed rather than silently fall back —
                # a misconfigured federation parent is a P0, not a P3.
                raise RuntimeError(
                    "remote-MCP transport selected but no RemoteMcpClient "
                    "is registered; the FastAPI lifespan must call "
                    "shared.mcp.server_remote.RemoteMcpClient.open() and "
                    "register via set_remote_mcp_client() at startup"
                )
            return remote.call(
                name, payload,
                feature_flag_required=feature_flag_required,
                actor_token_claims=actor_token_claims,
            )
        from shared.mcp.tools import TOOL_REGISTRY, discover_tools  # noqa: PLC0415

        # Always discover; idempotent. A "not empty" short-circuit would
        # miss tools added by modules that haven't been transitively
        # imported yet (see shared/api/app.py mcp_loaded note).
        discover_tools("shared.mcp.tools")
        spec = TOOL_REGISTRY.get(name)
        if spec is None:
            raise KeyError(f"MCP tool not registered: {name!r}")
        validated = spec.input_model.model_validate(payload)
        response = spec.fn(validated)
        return (
            response.model_dump(mode="json")
            if hasattr(response, "model_dump")
            else dict(response)
        )

    async def acall(
        self,
        name: str,
        payload: dict[str, Any],
        *,
        feature_flag_required: Optional[str] = None,
        actor_token_claims: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Async variant — preferred path for new FastAPI routes."""
        if self._transport.kind == "remote":
            remote = _REMOTE_MCP_CLIENT
            if remote is None:
                raise RuntimeError(
                    "remote-MCP transport selected but no RemoteMcpClient "
                    "is registered; see set_remote_mcp_client()."
                )
            return await remote.acall(
                name, payload,
                feature_flag_required=feature_flag_required,
                actor_token_claims=actor_token_claims,
            )
        # In-process — sync work, just rewrap.
        return self.call(
            name, payload,
            feature_flag_required=feature_flag_required,
            actor_token_claims=actor_token_claims,
        )


def get_mcp_client() -> McpClient:
    """FastAPI dependency: a fresh ``McpClient`` bound to the current transport."""
    return McpClient(_MCP_TRANSPORT)


# Alias preserved for any caller importing the historical name.
mcp_client = get_mcp_client


# ---------------------------------------------------------------------------
# Per-request convenience helpers
# ---------------------------------------------------------------------------


def actor_label(user: User) -> str:
    """Return the canonical actor label for audit rows.

    ``User.username`` is the Keycloak ``preferred_username``; falling back
    to ``email`` and finally the immutable ``sub`` keeps the audit trail
    legible even when one of those fields is unset.
    """
    return user.username or user.email or user.id


__all__: list[str] = [
    # Pool surface
    "DbHandle",
    "DbPoolNotInitialized",
    "init_db_pool",
    "close_db_pool",
    "set_db_pool",
    "get_db_pool",
    "get_db_pool_raw",
    # MCP surface
    "McpClient",
    "McpTransport",
    "get_mcp_client",
    "mcp_client",
    "set_mcp_transport",
    "get_mcp_transport",
    "set_remote_mcp_client",
    "get_remote_mcp_client",
    # Identity surface
    "current_user",
    "optional_user",
    "actor_label",
    # Hub loop (sync MCP → async DB)
    "set_hub_event_loop",
    "get_hub_event_loop",
    # Vault paths
    "DSN_VAULT_PATH",
]
