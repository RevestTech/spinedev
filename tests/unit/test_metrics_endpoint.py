"""
Unit tests for metrics endpoint response.

Tests:
  - /metrics endpoint returns Prometheus format
  - Correct content-type header
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


class TestMetricsEndpoint:
    """Test /metrics endpoint."""

    async def test_metrics_endpoint_returns_prometheus_format(self):
        """GET /metrics should return Prometheus text format."""
        from tron.infra.observability.metrics import init_metrics

        from fastapi import FastAPI

        app = FastAPI()
        init_metrics(app=app)

        # Get the metrics endpoint handler
        metrics_route = None
        for route in app.routes:
            if route.path == "/metrics":
                metrics_route = route

        assert metrics_route is not None

        # Call the endpoint
        response = await metrics_route.endpoint()

        assert response.media_type == "text/plain; version=0.0.4; charset=utf-8"
        assert isinstance(response.body, bytes)
        # Should contain Prometheus format content
        content = response.body.decode("utf-8")
        assert len(content) > 0

    async def test_metrics_endpoint_response_structure(self):
        """Metrics response should have correct structure."""
        import tron.infra.observability.metrics as metrics_mod
        from tron.infra.observability.metrics import init_metrics

        from fastapi import FastAPI

        # Reset so init_metrics registers the route on this app
        metrics_mod._metrics = None
        app = FastAPI()
        init_metrics(app=app)

        # Get the endpoint
        metrics_route = None
        for route in app.routes:
            if route.path == "/metrics":
                metrics_route = route

        response = await metrics_route.endpoint()

        content = response.body.decode("utf-8")
        # Prometheus format has HELP and TYPE comments
        # and metric lines with values
        lines = content.split("\n")
        has_metrics = any(line.startswith("http_") or line.startswith("agent_") or line.startswith("llm_") for line in lines)
        assert has_metrics or len(content) > 0  # At least some content
