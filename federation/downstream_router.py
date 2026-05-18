"""
federation.downstream_router
============================

Route requests from this Hub to **child Hubs** (#10 fractal federation +
#4 control plane / data plane split).

When a parent Hub needs to invoke a delegated tool on a specific child
(e.g. "ask the EMEA division Hub for its current incident count") or
broadcast (e.g. "push this signed bundle to every child for approval")
it goes through this router.

The router reads the child set from `HubRegistry.list_children` and
opens one mTLS+bearer channel per child using `UpstreamClient` (yes —
the upstream-client class is reused because mTLS+bearer is symmetric;
the only difference is the base_url and the per-child vault role).

Consent gating: every outbound delegated-tool call funnels through
`ConsentEngine.is_allowed(child, consent_class)`. The engine refuses
calls that the child has not explicitly consented to, or that the
bundle has not declared as a mandatory upward flow.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable, Optional
from uuid import UUID

from .hub_registry import HubRecord, HubRegistry
from .upstream_client import UpstreamClient, UpstreamClientConfig

logger = logging.getLogger("spine.federation.downstream_router")

#: Hard cap on concurrent child fan-out. Prevents a 100-child cascade
#: from saturating the local Hub's connection pool.
DEFAULT_MAX_CONCURRENCY = 16


class RoutingError(RuntimeError):
    """Raised when a downstream call cannot be issued (consent denied,
    child missing, etc.). Network-level errors surface as
    ``UpstreamCallError`` from the underlying client."""


@dataclass(frozen=True)
class _ChildCallOutcome:
    """One child's response in a broadcast."""

    hub_id: UUID
    ok: bool
    data: dict[str, Any]
    error: Optional[str] = None


class DownstreamRouter:
    """Route delegated tools / broadcasts to child Hubs.

    Construction takes the local Hub's `hub_id`, the `HubRegistry`, and
    an `is_allowed_callback` that mirrors `ConsentEngine.is_allowed`.
    Tests pass a trivial lambda; production wires the engine.
    """

    def __init__(
        self,
        *,
        local_hub_id: UUID,
        registry: HubRegistry,
        is_allowed: Callable[[UUID, str], Awaitable[bool]],
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        client_factory: Optional[
            Callable[[UpstreamClientConfig], "_ClientCtx"]
        ] = None,
    ) -> None:
        self._local_hub_id = local_hub_id
        self._registry = registry
        self._is_allowed = is_allowed
        self._max_concurrency = max(1, max_concurrency)
        # Allows tests to inject a fake context-manager factory in place
        # of `UpstreamClient.connect`. In production we let the default
        # (UpstreamClient.connect) handle TLS + bearer fetch.
        self._client_factory = client_factory

    # ---------------------------------------------------------------
    # Single-target routing
    # ---------------------------------------------------------------

    async def call_child(
        self,
        child_hub_id: UUID,
        *,
        method: str,
        path: str,
        consent_class: str,
        json: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Issue one delegated call to ``child_hub_id``.

        Steps:

        1. Lookup the child record (404 → RoutingError).
        2. Ask the consent engine; deny → RoutingError.
        3. Open the upstream channel; issue the call; return JSON.
        """
        child = await self._registry.get_by_hub_id(child_hub_id)
        if child is None:
            raise RoutingError(f"child hub {child_hub_id} not registered")
        if child.consent_status not in ("active",):
            raise RoutingError(
                f"child hub {child_hub_id} consent_status={child.consent_status!r} "
                "blocks delegated calls"
            )
        if not await self._is_allowed(child_hub_id, consent_class):
            raise RoutingError(
                f"child hub {child_hub_id} did not consent to {consent_class!r}"
            )
        cfg = UpstreamClientConfig(base_url=child.base_url, role="downstream")
        ctx = self._open_client(cfg)
        async with ctx as client:
            return await client.request(method, path, json=json)

    # ---------------------------------------------------------------
    # Broadcast routing
    # ---------------------------------------------------------------

    async def broadcast(
        self,
        *,
        method: str,
        path: str,
        consent_class: str,
        json: Optional[dict[str, Any]] = None,
        children: Optional[Iterable[HubRecord]] = None,
    ) -> list[_ChildCallOutcome]:
        """Fan out to every consenting child; return per-child outcomes.

        Errors do NOT abort the broadcast — each child gets a
        ``_ChildCallOutcome`` so the cascade can surface partial-failure
        UX to the operator. Concurrency is capped at
        ``self._max_concurrency``.
        """
        if children is None:
            children = await self._registry.list_children(self._local_hub_id)
        sem = asyncio.Semaphore(self._max_concurrency)
        outcomes: list[_ChildCallOutcome] = []

        async def _one(child: HubRecord) -> _ChildCallOutcome:
            async with sem:
                try:
                    data = await self.call_child(
                        child.hub_id,
                        method=method,
                        path=path,
                        consent_class=consent_class,
                        json=json,
                    )
                    return _ChildCallOutcome(
                        hub_id=child.hub_id, ok=True, data=data
                    )
                except Exception as exc:  # noqa: BLE001 - capture-all-by-design
                    logger.info(
                        "child_call_failed",
                        extra={"child_hub_id": str(child.hub_id), "error": str(exc)},
                    )
                    return _ChildCallOutcome(
                        hub_id=child.hub_id, ok=False, data={}, error=str(exc)
                    )

        tasks = [asyncio.create_task(_one(c)) for c in children]
        for t in asyncio.as_completed(tasks):
            outcomes.append(await t)
        return outcomes

    # ---------------------------------------------------------------
    # Internal — factory indirection for testability
    # ---------------------------------------------------------------

    def _open_client(self, cfg: UpstreamClientConfig) -> "_ClientCtx":
        """Return an async context manager that yields an UpstreamClient.

        In production this delegates to ``UpstreamClient.connect``; in
        tests we substitute a fake factory.
        """
        if self._client_factory is not None:
            return self._client_factory(cfg)
        return UpstreamClient.connect(cfg)  # type: ignore[return-value]


# Type alias for clarity — any object usable as `async with ctx as client`.
_ClientCtx = Any


__all__: list[str] = [
    "DownstreamRouter",
    "RoutingError",
    "DEFAULT_MAX_CONCURRENCY",
]
