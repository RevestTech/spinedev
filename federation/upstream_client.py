"""
federation.upstream_client
==========================

Async mTLS + bearer client for talking to a **parent Hub** (#4, #10).

Outbound channel from this Hub to its upstream. Used for:

* pulling signed bundles to apply locally (#16 update cascade — downward
  half of the tree),
* publishing security-incident events (when the bundle's mandatory
  upward-flow policy declares it — #10 bounded mandatory flows),
* heartbeating into the parent's federation status panel (#3 Hub UI
  aggregation).

Per #9 every secret routes through `shared.secrets`. Vault paths used:

    federation/mtls/<role>/cert      — PEM client certificate
    federation/mtls/<role>/key       — PEM client private key
    federation/bearer/<role>         — bearer token for the parent API

The `<role>` is the local Hub's role from the parent's perspective —
typically "child" for an organization's project Hubs reporting to a
corporate Hub. Operators can layer additional roles in the bundle.

The client is intentionally minimal: it builds an httpx.AsyncClient with
the right TLS material and exposes `request()` / `get()` / `post_json()`.
The MCP-level semantics (cascade gating, citation enforcement) live in
`update_cascade.py` and `consent.py`.
"""

from __future__ import annotations

import logging
import os
import ssl
import tempfile
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

try:  # pragma: no cover - optional at py_compile time
    import httpx  # type: ignore
except Exception:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

logger = logging.getLogger("spine.federation.upstream_client")

#: Vault path templates. Override via env metadata (#9 permits non-secret
#: path overrides). Production deployments leave these at defaults.
DEFAULT_CERT_PATH_TPL = os.environ.get(
    "SPINE_FED_MTLS_CERT_PATH_TPL", "federation/mtls/{role}/cert"
)
DEFAULT_KEY_PATH_TPL = os.environ.get(
    "SPINE_FED_MTLS_KEY_PATH_TPL", "federation/mtls/{role}/key"
)
DEFAULT_BEARER_PATH_TPL = os.environ.get(
    "SPINE_FED_BEARER_PATH_TPL", "federation/bearer/{role}"
)

#: Hard cap on the connect+read timeout for any single upstream call;
#: keeps the Hub event loop from stalling on a slow / dead parent.
DEFAULT_TIMEOUT_SECS = 20.0


class UpstreamCallError(RuntimeError):
    """Raised when an upstream call returns a non-2xx response or transport fails."""

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


@dataclass
class UpstreamClientConfig:
    """Inputs needed to build an UpstreamClient.

    The role is the *local* Hub's role from the parent's perspective.
    Most deployments only need "child", but bundles may declare
    additional roles (e.g. "security_reporter") for specific flows.
    """

    base_url: str
    role: str = "child"
    timeout_secs: float = DEFAULT_TIMEOUT_SECS
    verify: bool = True


class UpstreamClient:
    """One mTLS-authenticated channel to a parent Hub.

    Lifecycle: build via ``UpstreamClient.connect(cfg)`` (async context
    manager — fetches vault material, materializes a temp dir for the
    PEMs because httpx wants paths, then closes the httpx client and
    deletes the temp dir on exit).

    The vault-fetcher is injectable so tests can pass a callable that
    returns canned PEMs without touching `shared.secrets`.
    """

    def __init__(
        self,
        cfg: UpstreamClientConfig,
        *,
        http_client: Any,
        bearer_token: str,
        _cleanup: Optional[Callable[[], None]] = None,
    ) -> None:
        self._cfg = cfg
        self._client = http_client
        self._bearer = bearer_token
        self._cleanup = _cleanup

    # ---------------------------------------------------------------
    # Factory
    # ---------------------------------------------------------------

    @classmethod
    @asynccontextmanager
    async def connect(
        cls,
        cfg: UpstreamClientConfig,
        *,
        secret_fetcher: Optional[Callable[[str], Awaitable[str]]] = None,
    ) -> AsyncIterator["UpstreamClient"]:
        """Build a client with mTLS material fetched from vault.

        Vault paths (#9):
            federation/mtls/<role>/cert
            federation/mtls/<role>/key
            federation/bearer/<role>

        ``secret_fetcher`` defaults to `shared.secrets.get_secret` and is
        injectable for tests.
        """
        if httpx is None:  # pragma: no cover
            raise RuntimeError(
                "httpx is not installed; add `httpx` to your runtime env"
            )
        fetcher = secret_fetcher or _default_fetcher()
        cert_pem = await fetcher(DEFAULT_CERT_PATH_TPL.format(role=cfg.role))
        key_pem = await fetcher(DEFAULT_KEY_PATH_TPL.format(role=cfg.role))
        bearer = await fetcher(DEFAULT_BEARER_PATH_TPL.format(role=cfg.role))

        # httpx wants paths on disk for the client cert tuple.
        tmpdir = Path(tempfile.mkdtemp(prefix="spine-fed-mtls-"))
        cert_path = tmpdir / "client.crt"
        key_path = tmpdir / "client.key"
        cert_path.write_text(cert_pem, encoding="utf-8")
        key_path.write_text(key_pem, encoding="utf-8")
        try:
            cert_path.chmod(0o600)
            key_path.chmod(0o600)
        except OSError:  # pragma: no cover - non-POSIX
            pass

        ssl_ctx: Any
        if cfg.verify:
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.load_cert_chain(str(cert_path), str(key_path))
        else:
            ssl_ctx = False

        client = httpx.AsyncClient(
            base_url=cfg.base_url,
            timeout=cfg.timeout_secs,
            verify=ssl_ctx,
            headers={"Authorization": f"Bearer {bearer}"},
        )

        def _cleanup() -> None:
            try:
                for p in (cert_path, key_path):
                    if p.exists():
                        p.unlink()
                tmpdir.rmdir()
            except OSError:  # pragma: no cover
                pass

        try:
            yield cls(cfg, http_client=client, bearer_token=bearer, _cleanup=_cleanup)
        finally:
            await client.aclose()
            _cleanup()

    # ---------------------------------------------------------------
    # Calls
    # ---------------------------------------------------------------

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Issue one request; raise UpstreamCallError on non-2xx."""
        try:
            resp = await self._client.request(method, path, json=json, params=params)
        except Exception as exc:  # pragma: no cover - network-side
            logger.warning("upstream_transport_error", extra={"path": path})
            raise UpstreamCallError(
                f"transport error calling {self._cfg.base_url}{path}: {exc}",
                retryable=True,
            ) from exc
        if resp.status_code >= 400:
            retryable = 500 <= resp.status_code < 600
            raise UpstreamCallError(
                f"upstream {resp.status_code} on {method} {path}",
                status_code=resp.status_code,
                retryable=retryable,
            )
        try:
            return resp.json()
        except Exception:  # pragma: no cover - non-JSON 2xx
            return {"_raw": resp.text}

    async def get(
        self, path: str, *, params: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """Convenience GET; returns parsed JSON dict."""
        return await self.request("GET", path, params=params)

    async def post_json(
        self, path: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """Convenience POST with a JSON body."""
        return await self.request("POST", path, json=body)


def _default_fetcher() -> Callable[[str], Awaitable[str]]:
    """Return `shared.secrets.get_secret` (lazy import — keeps test isolation)."""
    from shared.secrets import get_secret  # noqa: PLC0415

    async def _fetch(path: str) -> str:
        return await get_secret(path)

    return _fetch


__all__: list[str] = [
    "UpstreamClient",
    "UpstreamClientConfig",
    "UpstreamCallError",
    "DEFAULT_CERT_PATH_TPL",
    "DEFAULT_KEY_PATH_TPL",
    "DEFAULT_BEARER_PATH_TPL",
]
