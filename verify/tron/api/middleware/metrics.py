"""
Request metrics middleware.

Records HTTP request duration and status counters using Prometheus
metrics. Unlike BaseHTTPMiddleware (which runs call_next in a thread
pool), this uses raw ASGI wrapping for zero-overhead, coverage-safe
instrumentation.
"""

from __future__ import annotations

import logging
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

# Paths to skip (health probes + metrics endpoint itself)
_SKIP_PATHS = {"/health", "/ready", "/metrics"}


class MetricsMiddleware:
    """ASGI middleware that records request latency and status counters."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in _SKIP_PATHS:
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        start = time.perf_counter()
        status_code = 500  # default if we never see a response

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)
            await send(message)

        try:
            # Track in-progress gauge
            try:
                from tron.infra.observability.metrics import get_metrics
                m = get_metrics()
                m.http_requests_in_progress.labels(method=method).inc()
            except RuntimeError:
                m = None

            await self.app(scope, receive, send_wrapper)

        finally:
            duration = time.perf_counter() - start

            try:
                from tron.infra.observability.metrics import record_http_request, get_metrics
                record_http_request(method, path, status_code, duration)
                if m:
                    m.http_requests_in_progress.labels(method=method).dec()
            except RuntimeError:
                pass  # Metrics not yet initialised (startup race)
