"""
Prometheus metrics for Tron.

Exposes a /metrics endpoint via prometheus-client and records:
  - HTTP request latency & status counters (via middleware)
  - Agent execution duration & finding counts
  - LLM call latency, token usage, and cost
  - Circuit-breaker state transitions
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    CollectorRegistry,
    REGISTRY,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


# ── Metric Definitions ──────────────────────────────────────────────


@dataclass
class TronMetrics:
    """Container for all application metrics."""

    # HTTP layer
    http_requests_total: Counter
    http_request_duration_seconds: Histogram
    http_requests_in_progress: Gauge

    # Agent layer
    agent_runs_total: Counter
    agent_duration_seconds: Histogram
    agent_findings_total: Counter

    # LLM layer
    llm_calls_total: Counter
    llm_call_duration_seconds: Histogram
    llm_tokens_total: Counter
    llm_cost_usd_total: Counter
    llm_circuit_breaker_state: Gauge

    # Audit pipeline
    audit_runs_total: Counter
    audit_duration_seconds: Histogram


_metrics: Optional[TronMetrics] = None


def _safe_counter(name: str, doc: str, labels: list) -> Counter:
    """Create or retrieve an existing Counter."""
    try:
        return Counter(name, doc, labels)
    except ValueError:
        return REGISTRY._names_to_collectors[name]


def _safe_gauge(name: str, doc: str, labels: list) -> Gauge:
    try:
        return Gauge(name, doc, labels)
    except ValueError:
        return REGISTRY._names_to_collectors[name]


def _safe_histogram(name: str, doc: str, labels: list, buckets=Histogram.DEFAULT_BUCKETS) -> Histogram:
    try:
        return Histogram(name, doc, labels, buckets=buckets)
    except ValueError:
        return REGISTRY._names_to_collectors[name]


def _create_metrics() -> TronMetrics:
    """Create all Prometheus metric objects (idempotent — reuses existing)."""
    return TronMetrics(
        # HTTP
        http_requests_total=_safe_counter(
            "http_requests_total", "Total HTTP requests",
            ["method", "path", "status"],
        ),
        http_request_duration_seconds=_safe_histogram(
            "http_request_duration_seconds", "HTTP request latency in seconds",
            ["method", "path"],
            buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
        ),
        http_requests_in_progress=_safe_gauge(
            "http_requests_in_progress", "HTTP requests currently being processed",
            ["method"],
        ),
        # Agents
        agent_runs_total=_safe_counter(
            "agent_runs_total", "Total agent executions",
            ["agent_type", "status"],
        ),
        agent_duration_seconds=_safe_histogram(
            "agent_duration_seconds", "Agent execution duration in seconds",
            ["agent_type"],
            buckets=(1, 5, 10, 30, 60, 120, 300),
        ),
        agent_findings_total=_safe_counter(
            "agent_findings_total", "Total findings produced by agents",
            ["agent_type", "severity"],
        ),
        # LLM
        llm_calls_total=_safe_counter(
            "llm_calls_total", "Total LLM API calls",
            ["provider", "model", "status"],
        ),
        llm_call_duration_seconds=_safe_histogram(
            "llm_call_duration_seconds", "LLM API call latency in seconds",
            ["provider", "model"],
            buckets=(0.5, 1, 2, 5, 10, 20, 30, 60),
        ),
        llm_tokens_total=_safe_counter(
            "llm_tokens_total", "Total tokens consumed",
            ["provider", "model", "direction"],
        ),
        llm_cost_usd_total=_safe_counter(
            "llm_cost_usd_total", "Cumulative LLM spend in USD",
            ["provider", "model"],
        ),
        llm_circuit_breaker_state=_safe_gauge(
            "llm_circuit_breaker_state",
            "LLM circuit breaker state (0=closed, 1=open, 2=half-open)",
            ["provider"],
        ),
        # Audit pipeline
        audit_runs_total=_safe_counter(
            "audit_runs_total", "Total audit pipeline executions",
            ["trigger_type", "status"],
        ),
        audit_duration_seconds=_safe_histogram(
            "audit_duration_seconds", "Audit pipeline duration in seconds",
            ["trigger_type"],
            buckets=(10, 30, 60, 120, 300, 600, 1200),
        ),
    )


def init_metrics(app=None) -> None:
    """Initialise metrics and attach the /metrics route.

    Idempotent — safe to call multiple times (e.g. in tests).
    """
    global _metrics
    if _metrics is not None:
        return  # already initialised
    _metrics = _create_metrics()

    if app is not None:
        @app.get("/metrics", include_in_schema=False)
        async def metrics_endpoint():
            """Prometheus scrape endpoint."""
            body = generate_latest()
            return Response(
                content=body,
                media_type=CONTENT_TYPE_LATEST,
            )

        logger.info("Prometheus /metrics endpoint registered")

    logger.info("Metrics initialised")


def get_metrics() -> TronMetrics:
    """Return the global metrics instance."""
    if _metrics is None:
        raise RuntimeError("Metrics not initialised. Call init_metrics() first.")
    return _metrics


# ── Convenience helpers ─────────────────────────────────────────────


def record_http_request(method: str, path: str, status: int, duration: float) -> None:
    """Record an HTTP request in all relevant metrics."""
    m = get_metrics()
    # Normalise path to remove UUIDs for cardinality control
    normalised = _normalise_path(path)
    m.http_requests_total.labels(method=method, path=normalised, status=str(status)).inc()
    m.http_request_duration_seconds.labels(method=method, path=normalised).observe(duration)


def record_llm_call(
    provider: str,
    model: str,
    status: str,
    duration: float,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
) -> None:
    """Record an LLM API call."""
    m = get_metrics()
    m.llm_calls_total.labels(provider=provider, model=model, status=status).inc()
    m.llm_call_duration_seconds.labels(provider=provider, model=model).observe(duration)
    if input_tokens:
        m.llm_tokens_total.labels(provider=provider, model=model, direction="input").inc(input_tokens)
    if output_tokens:
        m.llm_tokens_total.labels(provider=provider, model=model, direction="output").inc(output_tokens)
    if cost_usd:
        m.llm_cost_usd_total.labels(provider=provider, model=model).inc(cost_usd)


def record_agent_run(
    agent_type: str, status: str, duration: float,
    findings: int = 0, severity_counts: dict = None,
) -> None:
    """Record an ISO agent execution."""
    m = get_metrics()
    m.agent_runs_total.labels(agent_type=agent_type, status=status).inc()
    m.agent_duration_seconds.labels(agent_type=agent_type).observe(duration)
    if severity_counts:
        for sev, count in severity_counts.items():
            if count > 0:
                m.agent_findings_total.labels(agent_type=agent_type, severity=sev).inc(count)


def _normalise_path(path: str) -> str:
    """Replace UUID segments with {id} to limit label cardinality."""
    import re
    return re.sub(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        "{id}",
        path,
    )
