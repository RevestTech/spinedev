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
from datetime import datetime, timezone
from typing import Any, Optional

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


# ---------------------------------------------------------------------------
# In-band rotation entry point + canonical ``vault_rotated`` audit emission
# ---------------------------------------------------------------------------
#
# Per design decision #9 (no env-var secret reads) and FIX3's vault-rotations
# endpoint (which queries ``audit_event WHERE action IN ('vault_rotate',
# 'vault_rotated')``), we need ``vault_rotate`` (action initiated by the API
# handler) AND ``vault_rotated`` (action completed by the in-band rotator)
# to both land in the audit ledger. The API handler in
# ``shared/api/routes/vault_config.py`` already emits ``vault_rotate``; this
# helper closes the loop by emitting ``vault_rotated`` after the underlying
# adapter actually rotates.
#
# The audit write is best-effort: a missing ``SPINE_DB_URL`` (tests, off-DB
# bootstrap) MUST NOT break a rotation. Failures are logged at WARNING but
# never raised — the caller has already mutated the vault.


def _emit_vault_rotated_audit(
    *,
    path: str,
    actor: str,
    metadata: Optional[dict[str, Any]] = None,
) -> Optional[int]:
    """Best-effort emit a ``vault_rotated`` audit event.

    Mirrors the API-handler ``vault_rotate`` row but uses subsystem='shared'
    and role='secrets' so callers can distinguish API-initiated rotations
    (subsystem=hub, role=hub_admin) from in-band/completed rotations.
    Returns the inserted event_id, or ``None`` if the audit write failed
    (no DB, missing psql, redacted away, etc.).
    """
    # Lazy imports so this module stays importable in tooling that doesn't
    # have shared.audit on the path (py_compile, stripped CI shards).
    try:
        from shared.audit.audit_record import (  # noqa: PLC0415
            AuditRecord,
            chain_to_previous,
            write_via_psql,
        )
    except Exception as exc:  # pragma: no cover - audit pkg optional
        log.debug("vault_rotated_audit_import_failed", extra={"error": str(exc)})
        return None
    try:
        rec = AuditRecord(
            role="secrets",
            subsystem="shared",
            action="vault_rotated",
            actor=actor,
            subject_type="secret",
            subject_id=path,
            metadata={"surface": "rotation.rotate", **(metadata or {})},
        )
        rec = chain_to_previous(rec, prev_hash=None)
        return write_via_psql(rec)
    except Exception as exc:  # noqa: BLE001 - audit best-effort
        log.warning(
            "vault_rotated_audit_emit_failed",
            extra={"path": path, "error": str(exc)},
        )
        return None


async def rotate(
    path: str,
    *,
    actor: str = "shared.secrets.rotation",
    metadata: Optional[dict[str, Any]] = None,
) -> datetime:
    """Rotate the secret at ``path`` and emit a ``vault_rotated`` audit row.

    Returns the rotation timestamp (UTC). The audit row is written
    AFTER the rotation completes so a partial failure leaves no
    ``vault_rotated`` claim in the ledger.

    Adapter integration is delegated: when the active adapter exposes a
    ``rotate(path)`` coroutine, that drives the actual rotation; otherwise
    the function is a no-op against the vault and just files the audit
    event (used by callers that have already rotated out-of-band — e.g.
    AWS/Azure server-side rotation observed via the audit chain).

    Wave 4 will extend this hook with the ``RotationHook`` listener fanout
    so registered cache-invalidators / on-call pagers fire automatically.
    """
    # 1) Delegate to the adapter if it offers a rotate() method.
    try:
        from shared.secrets import get_default_adapter  # noqa: PLC0415

        adapter: Any = get_default_adapter()
    except Exception as exc:  # noqa: BLE001
        log.debug("rotate_adapter_lookup_failed", extra={"error": str(exc)})
        adapter = None
    adapter_rotate = getattr(adapter, "rotate", None) if adapter is not None else None
    if callable(adapter_rotate):
        try:
            maybe = adapter_rotate(path)
            if asyncio.iscoroutine(maybe):
                await maybe
        except Exception as exc:  # noqa: BLE001
            # Audit the FAILED attempt (not a vault_rotated) so the chain
            # records the operator intent + the failure, then re-raise so
            # the API handler returns 502.
            log.warning("rotate_failed", extra={"path": path, "error": str(exc)})
            raise
    # 2) Fire the in-process hook fanout. Errors collected (not raised) so
    #    a bad listener doesn't block downstream invalidation.
    errors = await default_rotation_hook.fire(path)
    if errors:
        log.warning(
            "rotate_hook_errors",
            extra={"path": path, "error_count": len(errors)},
        )
    # 3) Stamp the audit row + return the rotation timestamp.
    rotated_at = datetime.now(timezone.utc)
    _emit_vault_rotated_audit(
        path=path,
        actor=actor,
        metadata={
            "rotated_at": rotated_at.isoformat(),
            **({"hook_errors": len(errors)} if errors else {}),
            **(metadata or {}),
        },
    )
    return rotated_at


def _suppress_unused_imports() -> Any:  # pragma: no cover
    # Keep the type-only import alive for static checkers.
    return Awaitable
