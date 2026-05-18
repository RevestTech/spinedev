"""
shared/secrets/rotation.py
==========================

Rotation helpers.

For Vault / OpenBao:
    Dynamic-secret leases (DB creds, cloud creds via Vault's secret
    engines) must be renewed before they expire. `VaultLeaseRenewer`
    runs a background task that periodically calls
    `/v1/sys/leases/renew` with the lease id.

For AWS / Azure / GCP:
    Rotation is server-side; we expose `RotationHook` so the
    Hub UI / devops control plane can register callbacks that fire
    when a rotation event is observed in the audit chain. The hook
    machinery is intentionally light — the heavy lifting happens
    in the respective cloud's rotation system; we just give Spine
    a place to react (invalidate caches, page on-call, log evidence).

This module is best-effort scaffolding for Wave 0 — full integration
with the devops control plane lands in Wave 4 once `evidence/` and
`devops/` exist.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover - documented dep
    httpx = None  # type: ignore[assignment]

from .base import (
    SecretAccessDenied,
    SecretBackendError,
    SecretNotFound,
)


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Vault lease renewal
# ---------------------------------------------------------------------------


@dataclass
class _LeaseState:
    lease_id: str
    increment_seconds: int
    next_renew_at: float


class VaultLeaseRenewer:
    """Background renewer for Vault dynamic-secret leases.

    Typical usage:

        renewer = VaultLeaseRenewer(
            vault_url="https://vault.example:8200",
            token=token,
        )
        renewer.track(lease_id, increment_seconds=3600)
        await renewer.start()
        ...
        await renewer.stop()

    Renewal cadence: each lease is renewed at half its increment
    (i.e. a 3600s lease renews every 1800s). This gives a buffer
    against clock skew, slow renewals, and transient 5xx.
    """

    def __init__(
        self,
        vault_url: str,
        token: str,
        *,
        namespace: str | None = None,
        client: "httpx.AsyncClient | None" = None,
    ) -> None:
        if httpx is None and client is None:
            raise SecretBackendError(
                "httpx is required for VaultLeaseRenewer"
            )
        self._url = vault_url.rstrip("/")
        self._token = token
        self._namespace = namespace
        self._owned_client = client is None
        self._client = client or httpx.AsyncClient(timeout=10.0)
        self._leases: dict[str, _LeaseState] = {}
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    def track(self, lease_id: str, *, increment_seconds: int) -> None:
        """Register a lease to be renewed periodically."""
        if increment_seconds <= 0:
            raise ValueError("increment_seconds must be positive")
        loop_time = asyncio.get_event_loop().time() if asyncio.get_event_loop().is_running() else 0.0
        self._leases[lease_id] = _LeaseState(
            lease_id=lease_id,
            increment_seconds=increment_seconds,
            next_renew_at=loop_time + (increment_seconds / 2),
        )

    def untrack(self, lease_id: str) -> None:
        self._leases.pop(lease_id, None)

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(), name="vault-lease-renewer")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            try:
                await self._task
            except asyncio.CancelledError:  # pragma: no cover
                pass
            self._task = None
        if self._owned_client:
            await self._client.aclose()

    async def renew_now(self, lease_id: str) -> None:
        """Force an immediate renewal — primarily for tests / manual ops."""
        state = self._leases.get(lease_id)
        if state is None:
            raise SecretNotFound(f"lease {lease_id} not tracked")
        await self._renew(state)

    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        while not self._stop_event.is_set():
            now = asyncio.get_event_loop().time()
            for state in list(self._leases.values()):
                if state.next_renew_at <= now:
                    try:
                        await self._renew(state)
                    except Exception as exc:  # noqa: BLE001
                        log.warning(
                            "vault lease renewal failed for %s: %s",
                            state.lease_id,
                            exc,
                        )
            # Sleep until next tick OR stop signal (whichever comes first).
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                continue

    async def _renew(self, state: _LeaseState) -> None:
        url = f"{self._url}/v1/sys/leases/renew"
        headers = {"X-Vault-Token": self._token}
        if self._namespace:
            headers["X-Vault-Namespace"] = self._namespace
        body = {
            "lease_id": state.lease_id,
            "increment": state.increment_seconds,
        }
        response = await self._client.post(url, headers=headers, json=body)
        if response.status_code in (401, 403):
            raise SecretAccessDenied(
                f"vault denied lease renewal for {state.lease_id}"
            )
        if response.status_code == 404:
            # Lease has already expired / been revoked.
            self.untrack(state.lease_id)
            raise SecretNotFound(
                f"vault lease {state.lease_id} no longer exists"
            )
        if not 200 <= response.status_code < 300:
            raise SecretBackendError(
                f"vault lease renewal failed ({response.status_code})"
            )
        # Schedule next renewal at half-life.
        state.next_renew_at = asyncio.get_event_loop().time() + (
            state.increment_seconds / 2
        )


# ---------------------------------------------------------------------------
# Generic rotation hook registry (cloud adapters)
# ---------------------------------------------------------------------------


RotationCallback = Callable[[str], Awaitable[None]]


@dataclass
class RotationHook:
    """Cross-cloud rotation reaction registry.

    Wave 0 scope: in-process registry only. Wave 4 will wire this
    into the audit chain so that rotation events observed on
    AWS/Azure/GCP fire the registered callbacks automatically.

    Each callback takes the rotated secret path as its sole argument
    and should be idempotent (the same rotation may be observed
    multiple times by separate collectors).
    """

    callbacks: dict[str, list[RotationCallback]] = field(default_factory=dict)

    def register(self, path: str, callback: RotationCallback) -> None:
        self.callbacks.setdefault(path, []).append(callback)

    def unregister(self, path: str, callback: RotationCallback) -> None:
        callbacks = self.callbacks.get(path, [])
        if callback in callbacks:
            callbacks.remove(callback)

    async def fire(self, path: str) -> list[BaseException]:
        """Invoke every callback for `path`; return any exceptions raised.

        Exceptions are collected (not raised) so that one bad listener
        doesn't block the others. Callers MAY then surface failures
        via the audit chain.
        """
        errors: list[BaseException] = []
        for callback in self.callbacks.get(path, []):
            try:
                await callback(path)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)
        return errors


# Module-level default registry — Wave 4 wires audit events to this.
default_rotation_hook = RotationHook()


def _suppress_unused_imports() -> Any:  # pragma: no cover
    # Keep the type-only import alive for static checkers.
    return Awaitable
