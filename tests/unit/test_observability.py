"""
Unit tests for the observability subsystem.

Tests tracing init/shutdown, metrics recording, structured logging,
and the metrics middleware.
"""

from __future__ import annotations

import json
import logging
import time
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tron.infra.observability.tracing import (
    get_tracer,
    init_tracing,
    record_exception,
    shutdown_tracing,
)
from tron.infra.observability.metrics import (
    TronMetrics,
    _create_metrics,
    _normalise_path,
    get_metrics,
    init_metrics,
    record_agent_run,
    record_http_request,
    record_llm_call,
)
from tron.infra.observability.logging import JSONFormatter, init_logging


# ── Tracing ─────────────────────────────────────────────────────────


class TestTracing:

    def test_init_and_shutdown(self):
        """Init creates a provider, shutdown cleans it up."""
        init_tracing(app=None)
        tracer = get_tracer("test")
        assert tracer is not None
        shutdown_tracing()

    def test_shutdown_idempotent(self):
        """Calling shutdown when not initialised is a no-op."""
        shutdown_tracing()  # should not raise

    def test_get_tracer_returns_tracer(self):
        init_tracing(app=None)
        tracer = get_tracer("my-module")
        assert tracer is not None
        shutdown_tracing()

    def test_record_exception_on_span(self):
        from opentelemetry import trace
        init_tracing(app=None)
        tracer = get_tracer("test")
        with tracer.start_as_current_span("test-span") as span:
            exc = ValueError("boom")
            record_exception(span, exc)
            assert span.status.status_code == trace.StatusCode.ERROR
        shutdown_tracing()

    def test_fastapi_instrumentation_with_app(self):
        """When passed an app, should attempt FastAPI instrumentation."""
        from fastapi import FastAPI
        app = FastAPI()
        init_tracing(app=app)
        # No exception → instrumentation registered (or import warning logged)
        shutdown_tracing()


# ── Metrics ─────────────────────────────────────────────────────────


class TestMetrics:

    def test_get_metrics_before_init_raises(self):
        import tron.infra.observability.metrics as mod
        saved = mod._metrics
        mod._metrics = None
        try:
            with pytest.raises(RuntimeError, match="not initialised"):
                get_metrics()
        finally:
            mod._metrics = saved

    def test_init_metrics_without_app(self):
        init_metrics(app=None)
        m = get_metrics()
        assert isinstance(m, TronMetrics)

    def test_init_metrics_with_app(self):
        from fastapi import FastAPI
        app = FastAPI()
        # Reset so we can test the route-registration path
        import tron.infra.observability.metrics as mod
        saved = mod._metrics
        mod._metrics = None
        try:
            init_metrics(app=app)
            routes = [r.path for r in app.routes]
            assert "/metrics" in routes
        finally:
            # Restore original to avoid double-registration issues
            mod._metrics = saved

    def test_init_metrics_idempotent(self):
        init_metrics(app=None)
        init_metrics(app=None)  # second call should be a no-op
        m = get_metrics()
        assert isinstance(m, TronMetrics)

    def test_record_http_request(self):
        init_metrics(app=None)
        # Should not raise
        record_http_request("GET", "/api/projects", 200, 0.05)
        record_http_request("POST", "/api/audits", 201, 0.12)
        record_http_request("GET", "/api/audits/aaa-bbb", 404, 0.01)

    def test_record_llm_call(self):
        init_metrics(app=None)
        record_llm_call(
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            status="success",
            duration=2.5,
            input_tokens=100,
            output_tokens=200,
            cost_usd=0.001,
        )

    def test_record_llm_call_minimal(self):
        init_metrics(app=None)
        record_llm_call(
            provider="openai", model="gpt-4o",
            status="error", duration=30.0,
        )

    def test_record_agent_run(self):
        init_metrics(app=None)
        record_agent_run(
            agent_type="security-iso",
            status="success",
            duration=45.0,
            findings=5,
            severity_counts={"critical": 1, "high": 2, "medium": 2, "low": 0},
        )

    def test_record_agent_run_no_severity(self):
        init_metrics(app=None)
        record_agent_run(
            agent_type="builder-iso",
            status="error",
            duration=10.0,
        )

    def test_normalise_path(self):
        assert _normalise_path("/api/projects") == "/api/projects"
        assert _normalise_path(
            "/api/audits/12345678-1234-1234-1234-123456789abc"
        ) == "/api/audits/{id}"
        assert _normalise_path(
            "/api/audits/12345678-1234-1234-1234-123456789abc/findings"
        ) == "/api/audits/{id}/findings"


# ── Structured Logging ──────────────────────────────────────────────


class TestJSONFormatter:

    def test_format_basic_record(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=1, msg="hello %s", args=("world",), exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["message"] == "hello world"
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test"
        assert "timestamp" in parsed

    def test_format_with_exception(self):
        formatter = JSONFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            record = logging.LogRecord(
                name="test", level=logging.ERROR, pathname="test.py",
                lineno=1, msg="failed", args=(), exc_info=sys.exc_info(),
            )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["exception"]["type"] == "ValueError"
        assert "traceback" in parsed

    def test_format_with_extra_fields(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=1, msg="audit started", args=(), exc_info=None,
        )
        record.audit_run_id = "abc-123"
        record.project_id = "proj-456"
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["audit_run_id"] == "abc-123"
        assert parsed["project_id"] == "proj-456"

    def test_format_debug_includes_source(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.DEBUG, pathname="/src/test.py",
            lineno=42, msg="debug msg", args=(), exc_info=None,
        )
        record.funcName = "my_function"
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["source"]["line"] == 42

    def test_format_includes_trace_context(self):
        """When a span is active, trace_id and span_id are included."""
        from opentelemetry import trace
        init_tracing(app=None)
        tracer = get_tracer("test")
        formatter = JSONFormatter()
        with tracer.start_as_current_span("test-span"):
            record = logging.LogRecord(
                name="test", level=logging.INFO, pathname="test.py",
                lineno=1, msg="traced", args=(), exc_info=None,
            )
            output = formatter.format(record)
            parsed = json.loads(output)
            assert "trace_id" in parsed
            assert "span_id" in parsed
            assert len(parsed["trace_id"]) == 32
        shutdown_tracing()


class TestInitLogging:

    def test_init_logging_configures_root(self):
        init_logging(level="WARNING")
        root = logging.getLogger()
        assert root.level == logging.WARNING
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JSONFormatter)
        # Restore for other tests
        init_logging(level="INFO")

    def test_init_logging_default_level(self):
        init_logging()
        root = logging.getLogger()
        assert root.level == logging.INFO


# ── Metrics Middleware ──────────────────────────────────────────────


class TestMetricsMiddleware:

    async def test_middleware_records_request(self):
        from tron.api.middleware.metrics import MetricsMiddleware

        init_metrics(app=None)

        call_count = 0

        async def mock_app(scope, receive, send):
            nonlocal call_count
            call_count += 1
            await send({"type": "http.response.start", "status": 200})
            await send({"type": "http.response.body", "body": b"ok"})

        middleware = MetricsMiddleware(mock_app)
        scope = {"type": "http", "path": "/api/projects", "method": "GET"}
        sent = []

        async def receive():
            return {"type": "http.request", "body": b""}

        async def send(msg):
            sent.append(msg)

        await middleware(scope, receive, send)
        assert call_count == 1
        assert sent[0]["status"] == 200

    async def test_middleware_skips_health(self):
        from tron.api.middleware.metrics import MetricsMiddleware

        init_metrics(app=None)
        called = False

        async def mock_app(scope, receive, send):
            nonlocal called
            called = True

        middleware = MetricsMiddleware(mock_app)
        scope = {"type": "http", "path": "/health", "method": "GET"}
        await middleware(scope, lambda: None, lambda m: None)
        assert called

    async def test_middleware_skips_non_http(self):
        from tron.api.middleware.metrics import MetricsMiddleware

        init_metrics(app=None)
        called = False

        async def mock_app(scope, receive, send):
            nonlocal called
            called = True

        middleware = MetricsMiddleware(mock_app)
        scope = {"type": "websocket", "path": "/ws"}
        await middleware(scope, lambda: None, lambda m: None)
        assert called


# ── Init / Shutdown ─────────────────────────────────────────────────


class TestObservabilityInit:

    async def test_init_and_shutdown(self):
        from tron.infra.observability import init_observability, shutdown_observability

        await init_observability(app=None)
        # Metrics should be available
        m = get_metrics()
        assert m is not None
        await shutdown_observability()


# ── Tracing ImportError Paths ───────────────────────────────────────


class TestTracingImportErrors:
    """Test graceful handling of missing optional instrumentors."""

    def test_otlp_exporter_import_error(self):
        """When OTLP exporter is missing, log warning and continue."""
        import sys
        from unittest.mock import patch

        # Mock the OTLP exporter import to raise ImportError
        with patch.dict(sys.modules, {"opentelemetry.exporter.otlp.proto.grpc.trace_exporter": None}):
            # Clear the provider to reset state
            import tron.infra.observability.tracing as tracing_mod
            tracing_mod._provider = None

            # Mock the import to raise ImportError
            import builtins
            original_import = builtins.__import__

            def mock_import(name, *args, **kwargs):
                if "otlp" in name:
                    raise ImportError("opentelemetry-exporter-otlp-proto-grpc not installed")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                # init_tracing should log warning and continue (not fail)
                init_tracing(app=None)
                # Should have created a provider even without OTLP exporter
                assert tracing_mod._provider is not None
                shutdown_tracing()

    def test_otlp_exporter_general_exception(self):
        """When OTLP exporter fails with general exception, log warning."""
        from unittest.mock import patch, MagicMock

        import tron.infra.observability.tracing as tracing_mod
        tracing_mod._provider = None

        # Mock the exporter class to raise an exception
        mock_exporter = MagicMock(side_effect=RuntimeError("Connection failed"))

        with patch("opentelemetry.exporter.otlp.proto.grpc.trace_exporter.OTLPSpanExporter", mock_exporter):
            init_tracing(app=None)
            # Should have created a provider despite the error
            assert tracing_mod._provider is not None
            shutdown_tracing()

    def test_fastapi_instrumentation_import_error(self):
        """When FastAPI instrumentor is missing, log warning."""
        from fastapi import FastAPI
        from unittest.mock import patch
        import tron.infra.observability.tracing as tracing_mod

        tracing_mod._provider = None
        app = FastAPI()

        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "fastapi" in name and "instrumentation" in name:
                raise ImportError("opentelemetry-instrumentation-fastapi not installed")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            init_tracing(app=app)
            assert tracing_mod._provider is not None
            shutdown_tracing()

    def test_sqlalchemy_instrumentation_import_error(self):
        """When SQLAlchemy instrumentor is missing, silently skip."""
        from unittest.mock import patch
        import tron.infra.observability.tracing as tracing_mod

        tracing_mod._provider = None

        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "sqlalchemy" in name and "instrumentation" in name:
                raise ImportError("opentelemetry-instrumentation-sqlalchemy not installed")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            init_tracing(app=None)
            assert tracing_mod._provider is not None
            shutdown_tracing()

    def test_redis_instrumentation_import_error(self):
        """When Redis instrumentor is missing, silently skip."""
        from unittest.mock import patch
        import tron.infra.observability.tracing as tracing_mod

        tracing_mod._provider = None

        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "redis" in name and "instrumentation" in name:
                raise ImportError("opentelemetry-instrumentation-redis not installed")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            init_tracing(app=None)
            assert tracing_mod._provider is not None
            shutdown_tracing()

    def test_httpx_instrumentation_import_error(self):
        """When httpx instrumentor is missing, silently skip."""
        from unittest.mock import patch
        import tron.infra.observability.tracing as tracing_mod

        tracing_mod._provider = None

        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "httpx" in name and "instrumentation" in name:
                raise ImportError("opentelemetry-instrumentation-httpx not installed")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            init_tracing(app=None)
            assert tracing_mod._provider is not None
            shutdown_tracing()
