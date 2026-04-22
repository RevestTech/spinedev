"""
Observability instrumentation for Tron.

Initialises OpenTelemetry tracing, Prometheus metrics, and structured
logging — all wired to the OTEL Collector configured in docker-compose.

Usage (in api/main.py lifespan):
    from tron.infra.observability import init_observability, shutdown_observability
    await init_observability(app)
    ...
    await shutdown_observability()
"""

from tron.infra.observability.tracing import init_tracing, shutdown_tracing
from tron.infra.observability.metrics import init_metrics, get_metrics
from tron.infra.observability.logging import init_logging

__all__ = [
    "init_observability",
    "shutdown_observability",
    "get_metrics",
]


async def init_observability(app=None) -> None:
    """Initialise all observability subsystems."""
    init_logging()
    init_tracing(app)
    init_metrics(app)


async def shutdown_observability() -> None:
    """Flush and tear down providers."""
    shutdown_tracing()
