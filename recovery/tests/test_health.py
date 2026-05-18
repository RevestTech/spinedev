"""Tests for ``recovery.health``."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from recovery.health import (
    HEALTH_COMPONENTS,
    HealthProber,
    HealthReport,
    HealthStatus,
    ProbeOutcome,
)


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# HTTP fetch fakes
# ---------------------------------------------------------------------------


class _FakeFetch:
    """Scriptable HTTP fetcher matching ``HealthProber._http_fetch`` shape."""

    def __init__(self, by_url: dict[str, tuple[int, str]]) -> None:
        self.by_url = by_url
        self.calls: list[str] = []

    async def __call__(self, url: str, timeout_s: float) -> tuple[int, str]:
        self.calls.append(url)
        if url not in self.by_url:
            raise RuntimeError(f"unscripted URL: {url}")
        return self.by_url[url]


async def _vault_ok() -> bool:
    return True


async def _vault_fail() -> bool:
    return False


# ---------------------------------------------------------------------------
# ProbeOutcome
# ---------------------------------------------------------------------------


class TestProbeOutcome:

    def test_is_ok(self) -> None:
        ok = ProbeOutcome(component="hub", status="healthy", latency_ms=5)
        not_ok = ProbeOutcome(component="hub", status="degraded", latency_ms=5)
        assert ok.is_ok is True
        assert not_ok.is_ok is False


# ---------------------------------------------------------------------------
# HealthReport
# ---------------------------------------------------------------------------


class TestHealthReport:

    def test_overall_healthy(self) -> None:
        outcomes = tuple(
            ProbeOutcome(component=c, status="healthy", latency_ms=1)
            for c in HEALTH_COMPONENTS
        )
        report = HealthReport(report_id=uuid4(),
                              generated_at=datetime.now(timezone.utc),
                              outcomes=outcomes)
        assert report.overall_status == "healthy"

    def test_overall_degraded(self) -> None:
        outcomes = (
            ProbeOutcome(component="hub", status="healthy", latency_ms=1),
            ProbeOutcome(component="vault", status="degraded", latency_ms=1),
        )
        report = HealthReport(report_id=uuid4(),
                              generated_at=datetime.now(timezone.utc),
                              outcomes=outcomes)
        assert report.overall_status == "degraded"

    def test_overall_unreachable_wins(self) -> None:
        outcomes = (
            ProbeOutcome(component="hub", status="healthy", latency_ms=1),
            ProbeOutcome(component="vault", status="degraded", latency_ms=1),
            ProbeOutcome(component="postgres", status="unreachable", latency_ms=1),
        )
        report = HealthReport(report_id=uuid4(),
                              generated_at=datetime.now(timezone.utc),
                              outcomes=outcomes)
        assert report.overall_status == "unreachable"

    def test_as_dict_shape(self) -> None:
        outcomes = (
            ProbeOutcome(component="hub", status="healthy", latency_ms=1,
                         detail="HTTP 200"),
        )
        report = HealthReport(report_id=uuid4(),
                              generated_at=datetime.now(timezone.utc),
                              outcomes=outcomes)
        d = report.as_dict()
        assert d["overall_status"] == "healthy"
        assert d["components"][0]["component"] == "hub"
        assert d["components"][0]["latency_ms"] == 1


# ---------------------------------------------------------------------------
# HealthProber per-component probes
# ---------------------------------------------------------------------------


class TestProbeHub:

    def test_200_is_healthy(self) -> None:
        fake = _FakeFetch({
            "http://localhost:8080/api/v2/health": (200, '{"ok":true}'),
        })
        prober = HealthProber(http_fetch=fake, vault_health_fn=_vault_ok)
        out = _run(prober.probe_hub())
        assert out.status == "healthy"

    def test_500_is_unreachable(self) -> None:
        fake = _FakeFetch({
            "http://localhost:8080/api/v2/health": (503, "guru meditation"),
        })
        prober = HealthProber(http_fetch=fake, vault_health_fn=_vault_ok)
        out = _run(prober.probe_hub())
        assert out.status == "unreachable"

    def test_404_is_degraded(self) -> None:
        fake = _FakeFetch({
            "http://localhost:8080/api/v2/health": (404, "no route"),
        })
        prober = HealthProber(http_fetch=fake, vault_health_fn=_vault_ok)
        out = _run(prober.probe_hub())
        assert out.status == "degraded"


class TestProbeKeycloak:

    def test_discovery_doc_missing_jwks(self) -> None:
        fake = _FakeFetch({
            "http://localhost:8443/realms/spine/.well-known/openid-configuration":
                (200, '{"issuer":"x"}'),
        })
        prober = HealthProber(http_fetch=fake, vault_health_fn=_vault_ok)
        out = _run(prober.probe_keycloak())
        assert out.status == "degraded"

    def test_discovery_doc_includes_jwks(self) -> None:
        fake = _FakeFetch({
            "http://localhost:8443/realms/spine/.well-known/openid-configuration":
                (200, '{"issuer":"x","jwks_uri":"http://jwks"}'),
        })
        prober = HealthProber(http_fetch=fake, vault_health_fn=_vault_ok)
        out = _run(prober.probe_keycloak())
        assert out.status == "healthy"


class TestProbeVault:

    def test_vault_ok(self) -> None:
        prober = HealthProber(http_fetch=_FakeFetch({}),
                              vault_health_fn=_vault_ok)
        out = _run(prober.probe_vault())
        assert out.status == "healthy"

    def test_vault_returns_false(self) -> None:
        prober = HealthProber(http_fetch=_FakeFetch({}),
                              vault_health_fn=_vault_fail)
        out = _run(prober.probe_vault())
        assert out.status == "degraded"

    def test_vault_raises_marks_unreachable(self) -> None:
        async def boom() -> bool:
            raise RuntimeError("backend down")

        prober = HealthProber(http_fetch=_FakeFetch({}),
                              vault_health_fn=boom)
        out = _run(prober.probe_vault())
        assert out.status == "unreachable"


class TestProbePostgres:

    def test_no_pool_yields_unknown(self) -> None:
        prober = HealthProber(http_fetch=_FakeFetch({}),
                              vault_health_fn=_vault_ok)
        out = _run(prober.probe_postgres())
        assert out.status == "unknown"

    def test_select_1_returns_one(self, mock_pool) -> None:
        mock_pool.script_scalar(1)
        prober = HealthProber(
            http_fetch=_FakeFetch({}), vault_health_fn=_vault_ok,
            pool_factory=lambda: mock_pool,
        )
        out = _run(prober.probe_postgres())
        assert out.status == "healthy"

    def test_select_1_returns_zero_is_degraded(self, mock_pool) -> None:
        mock_pool.script_scalar(0)
        prober = HealthProber(
            http_fetch=_FakeFetch({}), vault_health_fn=_vault_ok,
            pool_factory=lambda: mock_pool,
        )
        out = _run(prober.probe_postgres())
        assert out.status == "degraded"


class TestProbeMcpServer:

    def test_inprocess_registry(self) -> None:
        prober = HealthProber(
            http_fetch=_FakeFetch({}), vault_health_fn=_vault_ok,
            mcp_server_url=None,
        )
        out = _run(prober.probe_mcp_server())
        # Registry may be empty in a fresh process — both healthy and
        # degraded are acceptable. The contract is that the probe runs.
        assert out.status in ("healthy", "degraded")
        assert "tool_count" in out.diagnostic


# ---------------------------------------------------------------------------
# generate_report end-to-end
# ---------------------------------------------------------------------------


class TestGenerateReport:

    def test_all_healthy(self, mock_pool) -> None:
        mock_pool.script_scalar(1)
        fake = _FakeFetch({
            "http://localhost:8080/api/v2/health": (200, '{"ok":true}'),
            "http://localhost:8443/realms/spine/.well-known/openid-configuration":
                (200, '{"jwks_uri":"x"}'),
        })
        prober = HealthProber(
            http_fetch=fake, vault_health_fn=_vault_ok,
            pool_factory=lambda: mock_pool, mcp_server_url=None,
        )
        report = _run(prober.generate_report())
        # 5 components probed
        assert len(report.outcomes) == 5
        # At least the hub + vault + keycloak + postgres should be healthy
        statuses = {o.component: o.status for o in report.outcomes}
        assert statuses["hub"] == "healthy"
        assert statuses["vault"] == "healthy"
        assert statuses["keycloak"] == "healthy"
        assert statuses["postgres"] == "healthy"

    def test_emits_notify_on_degraded(self, mock_pool) -> None:
        notifies: list[tuple[str, str]] = []
        mock_pool.script_scalar(1)
        fake = _FakeFetch({
            "http://localhost:8080/api/v2/health": (500, "down"),
            "http://localhost:8443/realms/spine/.well-known/openid-configuration":
                (200, '{"jwks_uri":"x"}'),
        })
        prober = HealthProber(
            http_fetch=fake, vault_health_fn=_vault_ok,
            pool_factory=lambda: mock_pool, mcp_server_url=None,
            notify_fn=lambda s, b: notifies.append((s, b)),
        )
        report = _run(prober.generate_report())
        assert report.overall_status in ("degraded", "unreachable")
        assert notifies, "expected notifier to fire on degraded report"


# ---------------------------------------------------------------------------
# Heartbeat writer
# ---------------------------------------------------------------------------


class TestEmitHeartbeat:

    def test_writes_upsert(self, mock_pool) -> None:
        prober = HealthProber(
            http_fetch=_FakeFetch({}), vault_health_fn=_vault_ok,
            pool_factory=lambda: mock_pool,
        )
        src, tgt = uuid4(), uuid4()
        _run(prober.emit_heartbeat(source_hub_id=src, target_hub_id=tgt))
        assert any("spine_dr.heartbeat" in sql
                   for sql, _ in mock_pool.executes)
