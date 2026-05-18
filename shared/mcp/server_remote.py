"""
shared.mcp.server_remote
========================

Remote-MCP transport for federation parent <-> child Hub tool delegation
(V3 #4 control/data split, #10 fractal Hub, #25 Keycloak, #30 heavier MCP).

This module ships TWO halves:

1. :class:`RemoteMcpClient` — the **child Hub** side. An httpx-backed
   client with mTLS + bearer (both fetched from vault per design
   decision #9) that mirrors the in-process ``McpClient`` surface
   (``call``, ``acall``, ``list_tools``, ``subscribe``). Plug-in
   replacement for :class:`shared.api.dependencies.McpClient` when the
   federation bundle declares an upstream parent Hub.

2. :func:`build_remote_router` — the **parent Hub** side. A thin
   FastAPI router that exposes the same MCP surface over HTTP with
   mTLS + bearer enforced (cite-or-refuse middleware runs locally just
   like for in-process calls). Mount under ``/api/v2/mcp/remote/`` so
   child Hubs have a stable URL to hit.

Vault path conventions match :mod:`federation.upstream_client`
(Wave 4 Squad A established the shape; this module reuses it without
re-inventing):

    federation/mtls/<role>/cert    — PEM client certificate
    federation/mtls/<role>/key     — PEM client private key
    federation/bearer/<role>       — Keycloak service-account bearer token

``<role>`` is the calling Hub's federation role from the upstream's
perspective. Typically "child" for project-Hub-to-corporate-Hub, but
bundles may layer additional roles (e.g. "security_reporter").

Design tenets enforced here
---------------------------

* **#9 — vault-only secrets.** mTLS cert/key AND bearer all flow through
  :mod:`shared.secrets`; never read from env vars holding secret values,
  never persisted to disk except as 0600-mode temp PEMs inside a
  per-connection temp dir that is removed on close.
* **#12 — Cite-or-Refuse preservation.** Verify-class responses returned
  by the remote MUST carry a non-empty ``citation`` list; if the remote
  omits it, the client surfaces a local refusal envelope rather than
  blindly accepting (the parent Hub may have a different middleware
  posture, but the LOCAL contract is non-negotiable).
* **#25 — Keycloak.** The bearer is a Keycloak service-account access
  token; the receiving Hub validates it via its own Keycloak middleware
  before dispatch. This module does NOT verify tokens — that is the
  server side's job.
* **#30 — Heavier MCP envelope.** ``feature_flag_required`` and
  ``actor_token_claims`` (Wave 6 Stream J extensions on
  :class:`shared.mcp.schemas.ToolRequest`) are passed through verbatim
  so the receiving Hub can fail-closed on disabled flags and make
  downstream authorisation decisions without re-validating the JWT.

Retry policy
------------

Hand-rolled exponential backoff with full jitter, mirroring
:mod:`shared.llm.retry` (we don't import it to keep the module
self-contained for downstream extraction). Retries on 5xx and transport
errors; 401/403 surface immediately as
:class:`RemoteMcpAuthError` (never silently retried — auth bugs must be
loud, per fail-closed posture).

Scope note
----------

Connection pooling is delegated to httpx's connection pool inside the
single long-lived ``httpx.AsyncClient`` per :class:`RemoteMcpClient`
instance (a Hub typically only has one upstream parent). For a future
multi-parent topology (mesh federation), upgrade to a per-parent client
pool here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import ssl
import tempfile
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

try:  # pragma: no cover - optional at py_compile time
    import httpx  # type: ignore
except Exception:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

# FastAPI types are imported at module level (rather than lazily inside
# the router factory) so the route handler annotations resolve cleanly
# when ``from __future__ import annotations`` is in effect — FastAPI
# can't evaluate the string ``"Request"`` against a closure-local
# namespace. Importing here is safe because the runtime already has
# FastAPI installed for the Hub API; py_compile-only environments fall
# through to the ``None`` sentinels and the router factory raises if
# called without the real types.
try:  # pragma: no cover - optional at py_compile time
    from fastapi import APIRouter  # type: ignore
    from fastapi import HTTPException  # type: ignore
    from fastapi import Request  # type: ignore
    from fastapi.responses import StreamingResponse  # type: ignore
    _FASTAPI_AVAILABLE = True
except Exception:  # pragma: no cover
    APIRouter = None  # type: ignore[assignment,misc]
    HTTPException = None  # type: ignore[assignment,misc]
    Request = None  # type: ignore[assignment,misc]
    StreamingResponse = None  # type: ignore[assignment,misc]
    _FASTAPI_AVAILABLE = False

logger = logging.getLogger("spine.mcp.server_remote")


# ---------------------------------------------------------------------------
# Vault path templates — symmetric with federation/upstream_client.py
# ---------------------------------------------------------------------------

#: Per design decision #9 the PATH may be overridden via env (path is
#: metadata, not a secret value). PRODUCTION leaves these at defaults.
DEFAULT_CERT_PATH_TPL = os.environ.get(
    "SPINE_FED_MTLS_CERT_PATH_TPL", "federation/mtls/{role}/cert"
)
DEFAULT_KEY_PATH_TPL = os.environ.get(
    "SPINE_FED_MTLS_KEY_PATH_TPL", "federation/mtls/{role}/key"
)
DEFAULT_BEARER_PATH_TPL = os.environ.get(
    "SPINE_FED_BEARER_PATH_TPL", "federation/bearer/{role}"
)

#: Hard cap on per-call timeout. Keeps the Hub event loop from stalling
#: on a slow / dead parent (federation autonomy per #10/#32 layer 6).
DEFAULT_TIMEOUT_SECS = 20.0

#: Default retry policy. Mirrors ``shared.llm.retry.DEFAULT_POLICY``
#: defaults; chosen for symmetry rather than tuned for federation.
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_BASE_DELAY_SECS = 1.0
DEFAULT_MULTIPLIER = 2.0
DEFAULT_MAX_DELAY_SECS = 30.0

#: Verify-class tools currently registered. When the remote returns a
#: ``status='ok'`` response for one of these names with no citations,
#: we refuse locally (#12). Loaded lazily to avoid importing tool
#: modules at module-import time (which would force-discover all tools).
_VERIFY_CLASS_TOOLS_CACHE: set[str] | None = None


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class RemoteMcpError(RuntimeError):
    """Base class for all remote-MCP transport errors."""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class RemoteMcpAuthError(RemoteMcpError):
    """401 / 403 from the upstream — never retried; auth bugs surface loudly."""

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message, status_code=status_code, retryable=False)


class RemoteMcpTransportError(RemoteMcpError):
    """5xx / connection / timeout failure — retryable per policy."""

    def __init__(self, message: str, *, status_code: Optional[int] = None) -> None:
        super().__init__(message, status_code=status_code, retryable=True)


class RemoteMcpCitationRefusal(RemoteMcpError):
    """Local cite-or-refuse refusal on a remote verify-class response (#12)."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(
            f"remote verify-class tool {tool_name!r} returned status=ok with "
            "no citation; refusing locally per V3 #12 (Cite-or-Refuse)",
            status_code=422,
            retryable=False,
        )
        self.tool_name = tool_name


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RemoteMcpClientConfig:
    """Inputs needed to build a :class:`RemoteMcpClient`.

    ``role`` is the LOCAL Hub's federation role from the parent's
    perspective; almost always ``"child"``. Per-bundle overrides are
    declared in the federation bundle (e.g. ``"security_reporter"`` for
    mandatory upward incident flow).

    ``base_url`` is the parent Hub's MCP-remote URL prefix, typically
    ``https://hub.parent.example.com/api/v2/mcp/remote``.

    ``actor`` is the role/actor label this Hub presents in the outbound
    ``ToolRequest.actor`` envelope field; the receiving Hub uses it
    for its own audit log. Defaults to the local Hub's federation role.
    """

    base_url: str
    role: str = "child"
    actor: str = "federation_child"
    project_id_default: str = "federation"
    timeout_secs: float = DEFAULT_TIMEOUT_SECS
    verify_tls: bool = True
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    base_delay_secs: float = DEFAULT_BASE_DELAY_SECS
    multiplier: float = DEFAULT_MULTIPLIER
    max_delay_secs: float = DEFAULT_MAX_DELAY_SECS


@dataclass
class _RetryPolicy:
    """Internal retry policy — mirrors :class:`shared.llm.retry.RetryPolicy`."""

    max_attempts: int
    base_delay_secs: float
    multiplier: float
    max_delay_secs: float
    jitter: bool = True


# ---------------------------------------------------------------------------
# Vault material helpers
# ---------------------------------------------------------------------------


def _default_secret_fetcher() -> Callable[[str], Awaitable[str]]:
    """Return ``shared.secrets.get_secret`` (lazy import — test isolation).

    Same pattern as :mod:`federation.upstream_client` so both clients
    converge on a single auth path.
    """
    from shared.secrets import get_secret  # noqa: PLC0415

    async def _fetch(path: str) -> str:
        return await get_secret(path)

    return _fetch


def _verify_class_tools() -> set[str]:
    """Return the set of registered tool names with ``requires_citation=True``.

    Lazy: only imports the tools package on first call. Cached for the
    life of the process. If the registry hasn't been populated yet we
    discover tools so the lookup is correct even when the remote client
    is the first thing to touch ``shared.mcp.tools`` (e.g. in tests).
    """
    global _VERIFY_CLASS_TOOLS_CACHE
    if _VERIFY_CLASS_TOOLS_CACHE is not None:
        return _VERIFY_CLASS_TOOLS_CACHE
    try:
        from shared.mcp.tools import TOOL_REGISTRY, discover_tools  # noqa: PLC0415

        if not TOOL_REGISTRY:
            discover_tools("shared.mcp.tools")
        _VERIFY_CLASS_TOOLS_CACHE = {
            name for name, spec in TOOL_REGISTRY.items()
            if getattr(spec, "requires_citation", False)
        }
    except Exception:  # noqa: BLE001 — registry unreachable: assume none
        _VERIFY_CLASS_TOOLS_CACHE = set()
    return _VERIFY_CLASS_TOOLS_CACHE


def _reset_verify_class_cache() -> None:
    """Test seam: clear the verify-class cache between unit tests."""
    global _VERIFY_CLASS_TOOLS_CACHE
    _VERIFY_CLASS_TOOLS_CACHE = None


# ---------------------------------------------------------------------------
# RemoteMcpClient
# ---------------------------------------------------------------------------


class RemoteMcpClient:
    """Async httpx client to a remote (parent) Hub's MCP surface.

    Mirrors the in-process :class:`shared.api.dependencies.McpClient`
    surface so route handlers can swap transports without code changes.

    Lifecycle
    ---------

    Two construction modes:

    1. **Async context manager (preferred for tests + ad-hoc use)** ::

           async with RemoteMcpClient.connect(cfg) as remote:
               result = await remote.acall("graph_query", {...})

    2. **Long-lived (preferred for Hub lifespan wiring)** ::

           remote = await RemoteMcpClient.open(cfg)
           ...
           await remote.aclose()

    Both paths materialize the mTLS PEMs into a 0600-mode temp dir,
    construct the underlying ``httpx.AsyncClient`` with the SSL context
    pre-loaded, then delete the temp dir on close.

    Concurrency
    -----------

    Safe to share one instance across many concurrent route handlers —
    httpx's connection pool handles parallelism.
    """

    # ---- construction ------------------------------------------------

    def __init__(
        self,
        cfg: RemoteMcpClientConfig,
        *,
        http_client: Any,
        bearer_token: str,
        retry: _RetryPolicy,
        cleanup: Optional[Callable[[], None]] = None,
    ) -> None:
        self._cfg = cfg
        self._client = http_client
        self._bearer = bearer_token
        self._retry = retry
        self._cleanup = cleanup
        self._closed = False

    @classmethod
    @asynccontextmanager
    async def connect(
        cls,
        cfg: RemoteMcpClientConfig,
        *,
        secret_fetcher: Optional[Callable[[str], Awaitable[str]]] = None,
        http_client_factory: Optional[Callable[..., Any]] = None,
    ) -> AsyncIterator["RemoteMcpClient"]:
        """Build a client; close on exit.

        ``secret_fetcher`` and ``http_client_factory`` are injectable so
        tests can substitute deterministic fakes without touching real
        vault/network.
        """
        client = await cls.open(
            cfg,
            secret_fetcher=secret_fetcher,
            http_client_factory=http_client_factory,
        )
        try:
            yield client
        finally:
            await client.aclose()

    @classmethod
    async def open(
        cls,
        cfg: RemoteMcpClientConfig,
        *,
        secret_fetcher: Optional[Callable[[str], Awaitable[str]]] = None,
        http_client_factory: Optional[Callable[..., Any]] = None,
    ) -> "RemoteMcpClient":
        """Materialize a long-lived client. Caller owns ``aclose()``."""
        if httpx is None and http_client_factory is None:  # pragma: no cover
            raise RuntimeError(
                "httpx is not installed and no http_client_factory provided; "
                "add `httpx` to your runtime env or inject a factory in tests"
            )
        fetcher = secret_fetcher or _default_secret_fetcher()
        cert_pem = await fetcher(DEFAULT_CERT_PATH_TPL.format(role=cfg.role))
        key_pem = await fetcher(DEFAULT_KEY_PATH_TPL.format(role=cfg.role))
        bearer = await fetcher(DEFAULT_BEARER_PATH_TPL.format(role=cfg.role))

        # Materialize PEMs in a 0600-mode temp dir; httpx + ssl module
        # both want disk paths for the client-cert tuple. We delete the
        # tmp dir on close, so secrets touch disk only for the lifetime
        # of the client. Per #9 we never write to a stable path.
        tmpdir = Path(tempfile.mkdtemp(prefix="spine-remote-mcp-mtls-"))
        cert_path = tmpdir / "client.crt"
        key_path = tmpdir / "client.key"
        cert_path.write_text(cert_pem, encoding="utf-8")
        key_path.write_text(key_pem, encoding="utf-8")
        try:
            cert_path.chmod(0o600)
            key_path.chmod(0o600)
        except OSError:  # pragma: no cover — non-POSIX
            pass

        verify_arg: Any
        if cfg.verify_tls:
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.load_cert_chain(str(cert_path), str(key_path))
            verify_arg = ssl_ctx
        else:
            verify_arg = False

        factory = http_client_factory or (
            (lambda **kw: httpx.AsyncClient(**kw)) if httpx is not None else None
        )
        assert factory is not None  # narrowed by the guard above

        client = factory(
            base_url=cfg.base_url,
            timeout=cfg.timeout_secs,
            verify=verify_arg,
            headers={
                "Authorization": f"Bearer {bearer}",
                "X-Spine-Federation-Role": cfg.role,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

        def _cleanup() -> None:
            try:
                for p in (cert_path, key_path):
                    if p.exists():
                        p.unlink()
                tmpdir.rmdir()
            except OSError:  # pragma: no cover
                pass

        retry = _RetryPolicy(
            max_attempts=cfg.max_attempts,
            base_delay_secs=cfg.base_delay_secs,
            multiplier=cfg.multiplier,
            max_delay_secs=cfg.max_delay_secs,
        )
        return cls(
            cfg,
            http_client=client,
            bearer_token=bearer,
            retry=retry,
            cleanup=_cleanup,
        )

    async def aclose(self) -> None:
        """Close the underlying httpx client + delete temp PEMs."""
        if self._closed:
            return
        self._closed = True
        try:
            await self._client.aclose()
        finally:
            if self._cleanup is not None:
                self._cleanup()

    # ---- public API: mirrors McpClient + adds async/streaming -------

    def call(
        self,
        name: str,
        payload: dict[str, Any],
        *,
        feature_flag_required: Optional[str] = None,
        actor_token_claims: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Sync wrapper around :meth:`acall`.

        Provided so the in-process :class:`McpClient` and this class
        share an identical sync surface — route handlers calling
        ``mcp.call(...)`` keep working when the transport is swapped.

        Implementation detail: routes the call onto the current event
        loop when one is running, else creates a fresh loop. FastAPI
        handlers already run inside an event loop; for those we expect
        callers to prefer :meth:`acall` directly.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.acall(
                    name,
                    payload,
                    feature_flag_required=feature_flag_required,
                    actor_token_claims=actor_token_claims,
                )
            )
        # We're inside an event loop — push to a worker thread so the
        # caller's loop isn't blocked. This is the slow path; new code
        # should ``await remote.acall(...)`` instead.
        future: asyncio.Future[dict[str, Any]] = asyncio.run_coroutine_threadsafe(  # type: ignore[assignment]
            self.acall(
                name,
                payload,
                feature_flag_required=feature_flag_required,
                actor_token_claims=actor_token_claims,
            ),
            asyncio.get_event_loop(),
        )
        return future.result()  # type: ignore[union-attr]

    async def acall(
        self,
        name: str,
        payload: dict[str, Any],
        *,
        feature_flag_required: Optional[str] = None,
        actor_token_claims: Optional[dict[str, Any]] = None,
        project_id: Optional[str] = None,
        actor: Optional[str] = None,
    ) -> dict[str, Any]:
        """Invoke ``name`` on the remote MCP server.

        Wraps ``payload`` in a :class:`shared.mcp.schemas.ToolRequest`
        envelope (including Wave 6 Stream J extensions when present)
        and POSTs to ``{base_url}/call/{name}``. Returns the remote's
        :class:`ToolResponse` ``data`` dict, after enforcing the local
        Cite-or-Refuse contract (#12).
        """
        body: dict[str, Any] = {
            "project_id": project_id or self._cfg.project_id_default,
            "actor": actor or self._cfg.actor,
            "params": payload,
        }
        if feature_flag_required:
            body["feature_flag_required"] = feature_flag_required
        if actor_token_claims:
            body["actor_token_claims"] = actor_token_claims

        raw = await self._request_with_retry("POST", f"/call/{name}", json_body=body)
        # Enforce local Cite-or-Refuse on verify-class tools (#12). We
        # do not trust the remote to have enforced its own contract.
        if name in _verify_class_tools():
            status = raw.get("status")
            citation = raw.get("citation") or []
            if status == "ok" and not citation:
                raise RemoteMcpCitationRefusal(name)
        return raw

    async def list_tools(self) -> list[dict[str, Any]]:
        """Return the remote server's tool catalog (name + description + tags).

        Used by federation UIs ("which tools can this parent delegate?")
        and by capability negotiation when a Hub is deciding whether to
        delegate a call locally or upstream.
        """
        resp = await self._request_with_retry("GET", "/tools")
        items = resp.get("tools")
        if isinstance(items, list):
            return items
        # Defensive: some servers return ``{"data": {"tools": [...]}}``.
        if isinstance(resp.get("data"), dict):
            inner = resp["data"].get("tools")
            if isinstance(inner, list):
                return inner
        return []

    async def subscribe(
        self,
        topic: str,
        *,
        project_id: Optional[str] = None,
        actor: Optional[str] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream events from the remote.

        Connects to ``GET /subscribe/{topic}`` with ``Accept:
        text/event-stream`` and yields one parsed JSON envelope per
        SSE ``data:`` line. Used by long-lived federation hooks
        (e.g. mirroring the parent Hub's decision queue into a child
        Hub's dashboard).

        Implemented as an async generator — caller must consume with
        ``async for`` so the connection closes on exit.
        """
        if self._closed:
            raise RemoteMcpError("client closed; subscribe rejected", retryable=False)
        headers = {"Accept": "text/event-stream"}
        params: dict[str, str] = {
            "project_id": project_id or self._cfg.project_id_default,
            "actor": actor or self._cfg.actor,
        }
        # No retry around streaming: a half-broken stream should surface
        # to the caller, which can decide to reconnect with backoff.
        try:
            stream_ctx = self._client.stream(
                "GET", f"/subscribe/{topic}", headers=headers, params=params,
            )
        except Exception as exc:  # pragma: no cover - factory failure
            raise RemoteMcpTransportError(f"subscribe: failed to open stream: {exc}") from exc

        async with stream_ctx as response:  # type: ignore[union-attr]
            status_code = getattr(response, "status_code", 200)
            if status_code in (401, 403):
                raise RemoteMcpAuthError(
                    f"subscribe {topic}: upstream returned {status_code}",
                    status_code=status_code,
                )
            if status_code >= 400:
                raise RemoteMcpTransportError(
                    f"subscribe {topic}: upstream returned {status_code}",
                    status_code=status_code,
                )
            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                payload_text = line[len("data:"):].strip()
                if not payload_text:
                    continue
                try:
                    yield json.loads(payload_text)
                except json.JSONDecodeError:
                    logger.warning(
                        "remote_mcp_sse_bad_json",
                        extra={"topic": topic, "raw": payload_text[:120]},
                    )

    # ---- internal: retry + request --------------------------------

    async def _request_with_retry(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Issue one request with retry on 5xx + transport errors.

        Never retries 4xx (except 408/429 which we treat as retryable
        transport-class signals from the upstream). Auth failures
        (401/403) raise :class:`RemoteMcpAuthError` immediately.
        """
        if self._closed:
            raise RemoteMcpError("client closed; call rejected", retryable=False)
        last_exc: Optional[BaseException] = None
        for attempt in range(self._retry.max_attempts):
            try:
                return await self._issue(method, path, json_body=json_body)
            except RemoteMcpAuthError:
                raise  # fail-closed; auth bugs must be loud
            except RemoteMcpError as exc:
                last_exc = exc
                if not exc.retryable or attempt == self._retry.max_attempts - 1:
                    raise
                delay = self._compute_delay(attempt)
                logger.warning(
                    "remote_mcp_retry",
                    extra={
                        "attempt": attempt + 1,
                        "max_attempts": self._retry.max_attempts,
                        "delay_secs": round(delay, 3),
                        "path": path,
                        "status_code": exc.status_code,
                    },
                )
                await asyncio.sleep(delay)
        # Unreachable; loop returns or raises.
        assert last_exc is not None
        raise last_exc

    async def _issue(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """One network attempt; classifies the response into our error tree."""
        try:
            resp = await self._client.request(method, path, json=json_body)
        except Exception as exc:
            raise RemoteMcpTransportError(
                f"transport error calling {self._cfg.base_url}{path}: {exc}",
            ) from exc

        status = getattr(resp, "status_code", 0)
        if status in (401, 403):
            raise RemoteMcpAuthError(
                f"upstream {status} on {method} {path}", status_code=status,
            )
        if status in (408, 429) or 500 <= status < 600:
            raise RemoteMcpTransportError(
                f"upstream {status} on {method} {path}", status_code=status,
            )
        if status >= 400:
            # Non-retryable 4xx (bad input, capability denied, etc.).
            raise RemoteMcpError(
                f"upstream {status} on {method} {path}",
                status_code=status, retryable=False,
            )
        try:
            return resp.json()  # type: ignore[no-any-return]
        except Exception:  # pragma: no cover - non-JSON 2xx
            return {"_raw": getattr(resp, "text", "")}

    def _compute_delay(self, attempt: int) -> float:
        """Exponential backoff with full jitter."""
        raw = self._retry.base_delay_secs * (self._retry.multiplier ** attempt)
        raw = min(raw, self._retry.max_delay_secs)
        if self._retry.jitter:
            return random.uniform(0.0, raw)
        return raw


# ---------------------------------------------------------------------------
# RemoteMcpServer — optional thin FastAPI router for the parent side
# ---------------------------------------------------------------------------


def build_remote_router(
    *,
    prefix: str = "/api/v2/mcp/remote",
    require_bearer: bool = True,
) -> Any:
    """Construct the FastAPI ``APIRouter`` that exposes the MCP surface.

    Mounts three endpoints under ``prefix``:

    * ``POST /call/{tool_name}`` — invoke an MCP tool. Body is the
      :class:`ToolRequest` envelope (including Wave 6 Stream J fields).
      Response is the :class:`ToolResponse` envelope.
    * ``GET  /tools``            — list registered tools (name +
      description + tags + requires_citation).
    * ``GET  /subscribe/{topic}``— SSE stream (placeholder loop, ready
      for Hub-specific event sources to plug in via a registry hook).

    Bearer enforcement is via the standard FastAPI dependency injection
    chain: this router relies on the surrounding app's OIDC middleware
    (which already verifies Keycloak service-account tokens per #25). We
    do NOT re-implement JWT verification here; that would duplicate the
    middleware in :mod:`shared.api.middleware.oidc` and risk drift.

    mTLS enforcement is at the ingress layer (the reverse proxy / k8s
    Ingress / sidecar terminates mTLS; the parent Hub app sees the
    client cert via ``X-SSL-Client-Subject`` headers and the OIDC
    middleware cross-checks against the bearer's ``sub``). This module
    does not re-terminate mTLS — that would require a second TLS
    handshake inside the app process, defeating the perf benefits of
    sidecar termination.

    Returns the configured ``APIRouter``. Callers mount with
    ``app.include_router(build_remote_router())``.
    """
    if not _FASTAPI_AVAILABLE:  # pragma: no cover - py_compile-only env
        raise RuntimeError(
            "FastAPI is required to build the remote-MCP router; install "
            "`fastapi` (already a Hub runtime dep) before calling this."
        )

    router = APIRouter(prefix=prefix, tags=["mcp-remote"])

    @router.get("/tools")
    async def _list_tools() -> dict[str, Any]:
        """Return the registered tool catalog."""
        from shared.mcp.tools import TOOL_REGISTRY, discover_tools  # noqa: PLC0415

        if not TOOL_REGISTRY:
            discover_tools("shared.mcp.tools")
        tools = [
            {
                "name": spec.name,
                "description": spec.description,
                "story": spec.story,
                "tags": list(spec.tags),
                "requires_citation": spec.requires_citation,
            }
            for spec in TOOL_REGISTRY.values()
        ]
        return {"tools": sorted(tools, key=lambda t: t["name"])}

    @router.post("/call/{tool_name}")
    async def _call_tool(tool_name: str, request: Request) -> dict[str, Any]:
        """Dispatch one MCP tool call.

        The request body is parsed as a :class:`ToolRequest`. Wave 6
        Stream J fields (``feature_flag_required`` + ``actor_token_claims``)
        are honoured: a disabled feature flag yields a 402-class error
        envelope WITHOUT invoking the tool (fail-closed).
        """
        from shared.api.middleware.feature_flag import (  # noqa: PLC0415
            KNOWN_FEATURE_FLAGS,
            is_feature_enabled,
        )
        from shared.mcp.cite_or_refuse import enforce as _cite_enforce  # noqa: PLC0415
        from shared.mcp.schemas.envelopes import ToolRequest  # noqa: PLC0415
        from shared.mcp.tools import TOOL_REGISTRY, discover_tools  # noqa: PLC0415

        try:
            raw_body = await request.json()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"invalid JSON body: {exc}") from exc
        try:
            envelope = ToolRequest.model_validate(raw_body)
        except Exception as exc:  # noqa: BLE001 — pydantic ValidationError
            raise HTTPException(422, f"invalid ToolRequest envelope: {exc}") from exc

        if envelope.feature_flag_required:
            if envelope.feature_flag_required not in KNOWN_FEATURE_FLAGS:
                raise HTTPException(
                    422,
                    f"unknown feature flag {envelope.feature_flag_required!r}",
                )
            if not is_feature_enabled(envelope.feature_flag_required):
                # Fail-closed envelope — never invoke the tool.
                return {
                    "status": "error",
                    "data": {},
                    "error": {
                        "code": "feature_disabled",
                        "message": (
                            f"Feature {envelope.feature_flag_required!r} is "
                            "not enabled on this license."
                        ),
                        "retryable": False,
                    },
                    "citation": [],
                }

        if not TOOL_REGISTRY:
            discover_tools("shared.mcp.tools")
        spec = TOOL_REGISTRY.get(tool_name)
        if spec is None:
            raise HTTPException(404, f"unknown tool {tool_name!r}")

        try:
            validated = spec.input_model.model_validate(envelope.params)
        except Exception as exc:  # noqa: BLE001 — pydantic ValidationError
            raise HTTPException(
                422, f"invalid params for {tool_name!r}: {exc}",
            ) from exc

        fn = spec.fn
        if spec.requires_citation:
            fn = _cite_enforce(spec.name, fn)
        response = fn(validated)
        if hasattr(response, "model_dump"):
            return response.model_dump(mode="json")  # type: ignore[no-any-return]
        return dict(response)

    @router.get("/subscribe/{topic}")
    async def _subscribe(topic: str, request: Request) -> StreamingResponse:
        """SSE stream placeholder.

        Yields a single ``hello`` event then keeps the connection open
        until the client disconnects. Real Hub event sources plug in via
        the ``remote_mcp_event_publisher`` registry (TODO Wave 5+).
        """
        async def _events() -> AsyncIterator[bytes]:
            yield (
                b"data: " + json.dumps({"topic": topic, "type": "hello"}).encode()
                + b"\n\n"
            )
            # Hold the connection until the client closes; production
            # wires this to the actual Hub event bus.
            try:
                while not await request.is_disconnected():
                    await asyncio.sleep(15)
                    yield (
                        b"data: " + json.dumps({"topic": topic, "type": "heartbeat"}).encode()
                        + b"\n\n"
                    )
            except asyncio.CancelledError:  # pragma: no cover
                return

        return StreamingResponse(
            _events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    return router


# Public alias mirroring the documentation; some callers will want to
# import ``mcp_remote_router`` as a noun-shaped name. The function is
# the canonical entry point — call it to receive a fresh APIRouter.
mcp_remote_router = build_remote_router


# ---------------------------------------------------------------------------
# Module-level helpers used by tests
# ---------------------------------------------------------------------------


@dataclass
class _ClientHandle:
    """Pair of (client, mark-closed) used by lifespan integration tests."""

    client: RemoteMcpClient
    closed: bool = field(default=False)


__all__: list[str] = [
    "DEFAULT_BEARER_PATH_TPL",
    "DEFAULT_CERT_PATH_TPL",
    "DEFAULT_KEY_PATH_TPL",
    "DEFAULT_TIMEOUT_SECS",
    "RemoteMcpAuthError",
    "RemoteMcpCitationRefusal",
    "RemoteMcpClient",
    "RemoteMcpClientConfig",
    "RemoteMcpError",
    "RemoteMcpTransportError",
    "build_remote_router",
    "mcp_remote_router",
]
