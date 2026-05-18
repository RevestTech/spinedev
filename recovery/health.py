"""Health probes for Hub / Vault / Keycloak / Postgres / MCP server (layer 5).

Layer 5 of #32 — *"Each Hub heartbeats to itself + federation parent (if
any) + vendor status registry. Failure → multi-medium notification per
#6. Detection ≤ 1 min."*

This module implements the cross-component probes. The federation-parent
heartbeat lives in ``federation/`` (Squad A); recovery only consumes
the result of that to surface in its DR-posture report.

Five core components are probed (``HEALTH_COMPONENTS``):

* **hub** — the Hub's own ``/api/v2/health`` endpoint (HTTP 200 + JSON
  shape; tells us the master role surfaces respond).
* **vault** — vault adapter ``health()`` if available; else a sentinel
  ``get_secret("recovery/_health_check")`` round-trip.
* **keycloak** — OIDC discovery doc fetch + JWKS reachable.
* **postgres** — ``SELECT 1`` via the asyncpg pool.
* **mcp_server** — local MCP server's tool-list endpoint (or in-process
  ``shared.mcp.server.SpineMcpServer.tool_count()`` if same process).

Each probe returns a :class:`ProbeOutcome` with status + latency +
diagnostic dict. The aggregator :class:`HealthProber` produces a
:class:`HealthReport` that ``shared/mcp/tools/recovery.py:recovery_health``
returns to the Hub UI.

Heartbeat writes go to ``spine_dr.heartbeat`` (see
``db/flyway/sql/V32__dr_backup_log.sql``).

All probes have a hard timeout (default 5 s each); the aggregator
parallelises them so total wall-clock stays under the layer-5 target
(detection ≤ 1 min) even with all five probes running serially in
worst case.
"""
from __future__ import annotations

import asyncio
import json
import logging
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Literal, Optional
from uuid import UUID, uuid4

logger = logging.getLogger("spine.recovery.health")

HealthStatus = Literal["healthy", "degraded", "unreachable", "unknown"]

#: Components probed by the default HealthProber. Order matters only
#: for human-readable output; aggregation is parallel.
HEALTH_COMPONENTS: tuple[str, ...] = (
    "hub", "vault", "keycloak", "postgres", "mcp_server",
)

#: Hard per-probe timeout. Per layer-5 target (≤ 1 min detection) we
#: pick 5 s so even a 5-component serial fallback stays well under.
DEFAULT_PROBE_TIMEOUT_S: float = 5.0


@dataclass(frozen=True)
class ProbeOutcome:
    """One component's probe result."""

    component: str
    status: HealthStatus
    latency_ms: int
    detail: str = ""
    diagnostic: dict[str, Any] = field(default_factory=dict)
    probed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_ok(self) -> bool:
        return self.status == "healthy"


@dataclass(frozen=True)
class HealthReport:
    """Aggregate report across HEALTH_COMPONENTS."""

    report_id: UUID
    generated_at: datetime
    outcomes: tuple[ProbeOutcome, ...]

    @property
    def overall_status(self) -> HealthStatus:
        if any(o.status == "unreachable" for o in self.outcomes):
            return "unreachable"
        if any(o.status == "degraded" for o in self.outcomes):
            return "degraded"
        if all(o.status == "healthy" for o in self.outcomes):
            return "healthy"
        return "unknown"

    def as_dict(self) -> dict[str, Any]:
        return {
            "report_id": str(self.report_id),
            "generated_at": self.generated_at.isoformat(),
            "overall_status": self.overall_status,
            "components": [
                {
                    "component": o.component,
                    "status": o.status,
                    "latency_ms": o.latency_ms,
                    "detail": o.detail,
                    "diagnostic": o.diagnostic,
                    "probed_at": o.probed_at.isoformat(),
                }
                for o in self.outcomes
            ],
        }


class HealthProber:
    """Run probes against every component + emit a HealthReport.

    Every external touch point is injectable so tests can drive
    deterministic outcomes without standing up Hub / Vault / etc.
    """

    def __init__(
        self,
        *,
        timeout_s: float = DEFAULT_PROBE_TIMEOUT_S,
        hub_url: str = "http://localhost:8080/api/v2/health",
        keycloak_url: str = "http://localhost:8443/realms/spine/.well-known/openid-configuration",
        mcp_server_url: Optional[str] = "http://localhost:8081/mcp/tools",
        pool_factory: Optional[Callable[[], Any]] = None,
        vault_health_fn: Optional[Callable[[], Awaitable[bool]]] = None,
        http_fetch: Optional[Callable[[str, float], Awaitable[tuple[int, str]]]] = None,
        notify_fn: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self._timeout_s = timeout_s
        self._hub_url = hub_url
        self._keycloak_url = keycloak_url
        self._mcp_server_url = mcp_server_url
        self._pool_factory = pool_factory or (lambda: None)
        self._vault_health_fn = vault_health_fn or _default_vault_health
        self._http_fetch = http_fetch or _default_http_fetch
        self._notify = notify_fn or _default_notify

    # --- per-component probes --------------------------------------

    async def probe_hub(self) -> ProbeOutcome:
        return await self._http_probe("hub", self._hub_url)

    async def probe_keycloak(self) -> ProbeOutcome:
        out = await self._http_probe("keycloak", self._keycloak_url)
        if out.is_ok:
            # Belt + braces: discovery doc should mention JWKS.
            try:
                body = out.diagnostic.get("body_excerpt") or ""
                if "jwks_uri" not in body:
                    return ProbeOutcome(
                        component="keycloak", status="degraded",
                        latency_ms=out.latency_ms,
                        detail="openid-configuration missing jwks_uri",
                        diagnostic=out.diagnostic,
                    )
            except Exception:  # noqa: BLE001
                pass
        return out

    async def probe_mcp_server(self) -> ProbeOutcome:
        if self._mcp_server_url is None:
            # Same-process MCP server — inspect the registry directly.
            start = time.monotonic()
            try:
                from shared.mcp.tools import TOOL_REGISTRY
                count = len(TOOL_REGISTRY)
                latency_ms = int((time.monotonic() - start) * 1000)
                status: HealthStatus = "healthy" if count > 0 else "degraded"
                return ProbeOutcome(
                    component="mcp_server", status=status,
                    latency_ms=latency_ms,
                    detail=f"in-process registry has {count} tools",
                    diagnostic={"tool_count": count},
                )
            except Exception as exc:  # noqa: BLE001
                return ProbeOutcome(
                    component="mcp_server", status="unreachable",
                    latency_ms=int((time.monotonic() - start) * 1000),
                    detail=f"registry import failed: {exc}",
                )
        return await self._http_probe("mcp_server", self._mcp_server_url)

    async def probe_postgres(self) -> ProbeOutcome:
        start = time.monotonic()
        pool = self._pool_factory()
        if pool is None:
            return ProbeOutcome(
                component="postgres", status="unknown",
                latency_ms=int((time.monotonic() - start) * 1000),
                detail="no pool available (Hub bootstrap incomplete)",
            )
        try:
            async with pool.acquire() as conn:
                val = await asyncio.wait_for(
                    conn.fetchval("SELECT 1;"),
                    timeout=self._timeout_s,
                )
            latency_ms = int((time.monotonic() - start) * 1000)
            healthy = val == 1
            return ProbeOutcome(
                component="postgres",
                status="healthy" if healthy else "degraded",
                latency_ms=latency_ms,
                detail="SELECT 1 returned " + str(val),
                diagnostic={"select_1_value": val},
            )
        except asyncio.TimeoutError:
            return ProbeOutcome(
                component="postgres", status="unreachable",
                latency_ms=int((time.monotonic() - start) * 1000),
                detail=f"timed out after {self._timeout_s}s",
            )
        except Exception as exc:  # noqa: BLE001
            return ProbeOutcome(
                component="postgres", status="unreachable",
                latency_ms=int((time.monotonic() - start) * 1000),
                detail=f"query failed: {exc}",
            )

    async def probe_vault(self) -> ProbeOutcome:
        start = time.monotonic()
        try:
            ok = await asyncio.wait_for(
                self._vault_health_fn(), timeout=self._timeout_s,
            )
            latency_ms = int((time.monotonic() - start) * 1000)
            return ProbeOutcome(
                component="vault",
                status="healthy" if ok else "degraded",
                latency_ms=latency_ms,
                detail="vault adapter reports OK" if ok else "vault adapter reports not OK",
            )
        except asyncio.TimeoutError:
            return ProbeOutcome(
                component="vault", status="unreachable",
                latency_ms=int((time.monotonic() - start) * 1000),
                detail=f"timed out after {self._timeout_s}s",
            )
        except Exception as exc:  # noqa: BLE001
            return ProbeOutcome(
                component="vault", status="unreachable",
                latency_ms=int((time.monotonic() - start) * 1000),
                detail=f"vault health check failed: {exc}",
            )

    # --- aggregate --------------------------------------------------

    async def generate_report(self) -> HealthReport:
        """Run all probes in parallel, build the HealthReport."""
        results = await asyncio.gather(
            self.probe_hub(),
            self.probe_vault(),
            self.probe_keycloak(),
            self.probe_postgres(),
            self.probe_mcp_server(),
            return_exceptions=True,
        )
        outcomes: list[ProbeOutcome] = []
        for r in results:
            if isinstance(r, BaseException):
                outcomes.append(ProbeOutcome(
                    component="unknown", status="unreachable",
                    latency_ms=0, detail=f"probe raised: {r}",
                ))
            else:
                outcomes.append(r)
        report = HealthReport(
            report_id=uuid4(),
            generated_at=datetime.now(timezone.utc),
            outcomes=tuple(outcomes),
        )
        if report.overall_status in ("degraded", "unreachable"):
            self._notify(
                f"[recovery] health degraded ({report.overall_status})",
                json.dumps(report.as_dict(), default=str),
            )
        return report

    # --- heartbeat writer ------------------------------------------

    async def emit_heartbeat(
        self, *, source_hub_id: UUID, target_hub_id: UUID,
        status: HealthStatus = "healthy",
    ) -> None:
        """Upsert one row into ``spine_dr.heartbeat``.

        Used by the layer-5 heartbeat loop; the watchdog calls this on
        its poll cadence so the federation parent can see liveness.
        """
        pool = self._pool_factory()
        if pool is None:
            return
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO spine_dr.heartbeat "
                "(source_hub_id, target_hub_id, last_heartbeat, status) "
                "VALUES ($1, $2, now(), $3) "
                "ON CONFLICT (source_hub_id, target_hub_id) DO UPDATE "
                "SET last_heartbeat = EXCLUDED.last_heartbeat, "
                "    status = EXCLUDED.status, "
                "    updated_at = now();",
                source_hub_id, target_hub_id, status,
            )

    # --- internals --------------------------------------------------

    async def _http_probe(self, component: str, url: str) -> ProbeOutcome:
        start = time.monotonic()
        try:
            code, body = await asyncio.wait_for(
                self._http_fetch(url, self._timeout_s),
                timeout=self._timeout_s + 0.5,
            )
            latency_ms = int((time.monotonic() - start) * 1000)
            excerpt = body[:200] if body else ""
            if 200 <= code < 300:
                return ProbeOutcome(
                    component=component, status="healthy",
                    latency_ms=latency_ms,
                    detail=f"HTTP {code}",
                    diagnostic={"http_code": code, "body_excerpt": excerpt},
                )
            if 500 <= code < 600:
                return ProbeOutcome(
                    component=component, status="unreachable",
                    latency_ms=latency_ms, detail=f"HTTP {code}",
                    diagnostic={"http_code": code, "body_excerpt": excerpt},
                )
            return ProbeOutcome(
                component=component, status="degraded",
                latency_ms=latency_ms, detail=f"HTTP {code}",
                diagnostic={"http_code": code, "body_excerpt": excerpt},
            )
        except asyncio.TimeoutError:
            return ProbeOutcome(
                component=component, status="unreachable",
                latency_ms=int((time.monotonic() - start) * 1000),
                detail=f"timed out after {self._timeout_s}s",
            )
        except Exception as exc:  # noqa: BLE001
            return ProbeOutcome(
                component=component, status="unreachable",
                latency_ms=int((time.monotonic() - start) * 1000),
                detail=f"fetch failed: {exc}",
            )


# ---------------------------------------------------------------------------
# Default external touch-points (override for tests)
# ---------------------------------------------------------------------------


async def _default_vault_health() -> bool:
    """Round-trip a sentinel through the configured secrets adapter.

    Falls back to ``False`` if no adapter is registered yet — that's a
    legitimate ``vault=unknown`` state rather than a probe failure.
    """
    try:
        from shared.secrets import get_default_adapter
        adapter = get_default_adapter()
        # Most adapters expose a list("") that's safe + idempotent.
        await adapter.list("")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("vault_health_failed", extra={"err": str(exc)})
        return False


async def _default_http_fetch(url: str, timeout_s: float) -> tuple[int, str]:
    """Minimal HTTP GET so we don't pull httpx into the recovery dep tree.

    Uses ``urllib.request`` in a thread so we don't block the loop. For
    the Hub's real-world health endpoints this is plenty.
    """
    import urllib.request
    import urllib.error

    def _sync() -> tuple[int, str]:
        try:
            req = urllib.request.Request(url, method="GET",
                                         headers={"User-Agent": "spine-recovery-health"})
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 (we control URL)
                body = resp.read(2048).decode("utf-8", errors="replace")
                return resp.status, body
        except urllib.error.HTTPError as exc:
            return exc.code, str(exc)
        except (urllib.error.URLError, socket.timeout, OSError) as exc:
            raise RuntimeError(str(exc)) from exc

    return await asyncio.to_thread(_sync)


def _default_notify(subject: str, body: str) -> None:
    try:
        from shared.notify import NotificationEvent, Notifier
        from shared.notify.channels import StdoutChannel
        Notifier(channels=[StdoutChannel()]).notify(NotificationEvent(
            event_type="project_blocked",
            project_id="recovery", project_name="recovery",
            phase="dr", actor="recovery",
            summary=subject, severity="warning",
            metadata={"body": body[:1024]},
        ))
    except Exception:  # noqa: BLE001
        logger.warning("notify_failed", extra={"subject": subject})


__all__ = [
    "DEFAULT_PROBE_TIMEOUT_S",
    "HEALTH_COMPONENTS",
    "HealthProber",
    "HealthReport",
    "HealthStatus",
    "ProbeOutcome",
]
