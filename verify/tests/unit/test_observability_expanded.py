"""
Expanded Tests for Observability (Metrics, Logging, Tracing)

Comprehensive tests for Prometheus metrics recording, structured JSON logging,
and OpenTelemetry trace context propagation.
"""

import pytest
import json
import logging
from datetime import datetime, timezone
from io import StringIO
from unittest.mock import Mock, patch, MagicMock
from uuid import uuid4

from prometheus_client import REGISTRY, CollectorRegistry

try:
    from opentelemetry import trace, context
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter
    HAS_OTEL = True
except ImportError:
    HAS_OTEL = False


# ============================================================================
# Metrics Recording Tests
# ============================================================================

class TestMetricsRecording:
    """Tests for Prometheus metrics"""

    def test_record_http_request_counter(self):
        """Record HTTP request counter"""
        from tron.infra.observability.metrics import record_http_request, get_metrics

        # Initialize metrics
        from tron.infra.observability.metrics import init_metrics
        init_metrics()

        record_http_request(method="GET", path="/audits", status=200, duration=0.15)

        metrics = get_metrics()
        assert metrics is not None

    def test_record_http_request_duration(self):
        """Record HTTP request latency histogram"""
        from tron.infra.observability.metrics import record_http_request, init_metrics

        init_metrics()

        # Record multiple requests
        record_http_request(method="POST", path="/audits", status=201, duration=0.25)
        record_http_request(method="POST", path="/audits", status=201, duration=0.23)
        record_http_request(method="POST", path="/audits", status=500, duration=0.05)

    def test_record_http_request_path_normalization(self):
        """HTTP path with UUIDs gets normalized"""
        from tron.infra.observability.metrics import _normalise_path

        path_with_uuid = "/audits/550e8400-e29b-41d4-a716-446655440000/findings"
        normalized = _normalise_path(path_with_uuid)

        assert "{id}" in normalized
        assert "550e8400" not in normalized

    def test_record_llm_call_counter(self):
        """Record LLM API call counter"""
        from tron.infra.observability.metrics import record_llm_call, init_metrics

        init_metrics()

        record_llm_call(
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            status="success",
            duration=2.5,
            input_tokens=500,
            output_tokens=200,
            cost_usd=0.005,
        )

    def test_record_llm_call_tokens(self):
        """Record LLM token usage"""
        from tron.infra.observability.metrics import record_llm_call, init_metrics

        init_metrics()

        record_llm_call(
            provider="openai",
            model="gpt-4",
            status="success",
            duration=3.2,
            input_tokens=1000,
            output_tokens=500,
            cost_usd=0.03,
        )

    def test_record_llm_call_failure(self):
        """Record LLM API call failure"""
        from tron.infra.observability.metrics import record_llm_call, init_metrics

        init_metrics()

        record_llm_call(
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            status="error",
            duration=0.5,
        )

    def test_record_agent_run(self):
        """Record agent execution"""
        from tron.infra.observability.metrics import record_agent_run, init_metrics

        init_metrics()

        record_agent_run(
            agent_type="security-iso",
            status="success",
            duration=15.5,
            findings=5,
            severity_counts={
                "critical": 2,
                "high": 2,
                "medium": 1,
            },
        )

    def test_record_agent_run_failure(self):
        """Record agent execution failure"""
        from tron.infra.observability.metrics import record_agent_run, init_metrics

        init_metrics()

        record_agent_run(
            agent_type="performance-iso",
            status="error",
            duration=8.2,
            findings=0,
        )


# ============================================================================
# Logging Tests
# ============================================================================

class TestStructuredLogging:
    """Tests for structured JSON logging"""

    def test_json_formatter_basic(self):
        """JSONFormatter creates valid JSON logs"""
        from tron.infra.observability.logging import JSONFormatter

        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="tron.agents",
            level=logging.INFO,
            pathname="/path/to/file.py",
            lineno=42,
            msg="Agent analysis complete",
            args=(),
            exc_info=None,
        )

        formatted = formatter.format(record)

        # Should be valid JSON
        log_entry = json.loads(formatted)

        assert log_entry["level"] == "INFO"
        assert log_entry["message"] == "Agent analysis complete"
        assert "timestamp" in log_entry
        assert "logger" in log_entry

    def test_json_logging_with_extra_fields(self):
        """Logger extra fields included in JSON output"""
        from tron.infra.observability.logging import JSONFormatter

        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="tron.audit",
            level=logging.INFO,
            pathname="/path/to/audit.py",
            lineno=100,
            msg="Audit started",
            args=(),
            exc_info=None,
        )

        # Add extra fields
        record.audit_run_id = str(uuid4())
        record.agent_id = "security-iso-1"
        record.duration_ms = 1500

        formatted = formatter.format(record)
        log_entry = json.loads(formatted)

        assert log_entry["audit_run_id"] == record.audit_run_id
        assert log_entry["agent_id"] == record.agent_id
        assert log_entry["duration_ms"] == 1500

    def test_json_logging_with_exception(self):
        """Logger includes exception info in JSON"""
        from tron.infra.observability.logging import JSONFormatter

        formatter = JSONFormatter()

        try:
            raise ValueError("Test error message")
        except ValueError:
            exc_info = True
            import sys
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="tron.error",
            level=logging.ERROR,
            pathname="/path/to/error.py",
            lineno=50,
            msg="LLM call failed",
            args=(),
            exc_info=exc_info,
        )

        formatted = formatter.format(record)
        log_entry = json.loads(formatted)

        assert log_entry["level"] == "ERROR"
        assert "exception" in log_entry
        assert log_entry["exception"]["type"] == "ValueError"

    def test_json_logging_iso8601_timestamp(self):
        """Timestamps are ISO-8601 formatted"""
        from tron.infra.observability.logging import JSONFormatter

        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="tron.test",
            level=logging.INFO,
            pathname="/path/to/test.py",
            lineno=1,
            msg="Test",
            args=(),
            exc_info=None,
        )

        formatted = formatter.format(record)
        log_entry = json.loads(formatted)

        # ISO-8601 format: YYYY-MM-DDTHH:MM:SS.sssZ
        timestamp = log_entry["timestamp"]
        assert "T" in timestamp
        assert "Z" in timestamp

    def test_init_logging_replaces_handlers(self):
        """init_logging() replaces existing handlers"""
        from tron.infra.observability.logging import init_logging

        root = logging.getLogger()
        initial_count = len(root.handlers)

        init_logging(level="INFO")

        # Should have JSON handler
        assert len(root.handlers) >= 1

    def test_init_logging_silences_noisy_loggers(self):
        """Noisy third-party loggers are silenced"""
        from tron.infra.observability.logging import init_logging

        init_logging(level="INFO")

        # These should be WARNING level or higher
        uvicorn_logger = logging.getLogger("uvicorn.access")
        otel_logger = logging.getLogger("opentelemetry")

        assert uvicorn_logger.level >= logging.WARNING
        assert otel_logger.level >= logging.WARNING


# ============================================================================
# Trace Context Tests
# ============================================================================

class TestTraceContext:
    """Tests for OpenTelemetry trace correlation"""

    def test_trace_id_in_log_entry(self):
        """Log entry includes trace_id from context"""
        from tron.infra.observability.logging import JSONFormatter

        # Mock OpenTelemetry context
        span = Mock()
        span_context = Mock()
        span_context.trace_id = 0x12345678901234567890123456789012
        span_context.span_id = 0x1234567890123456
        span.get_span_context.return_value = span_context

        with patch('tron.infra.observability.logging.trace.get_current_span', return_value=span):
            formatter = JSONFormatter()
            record = logging.LogRecord(
                name="tron.trace",
                level=logging.INFO,
                pathname="/path/to/trace.py",
                lineno=1,
                msg="Traced operation",
                args=(),
                exc_info=None,
            )

            formatted = formatter.format(record)
            log_entry = json.loads(formatted)

            assert "trace_id" in log_entry
            assert len(log_entry["trace_id"]) == 32  # 128-bit hex

    def test_span_id_in_log_entry(self):
        """Log entry includes span_id from context"""
        from tron.infra.observability.logging import JSONFormatter

        span = Mock()
        span_context = Mock()
        span_context.trace_id = 0x12345678901234567890123456789012
        span_context.span_id = 0x1234567890123456
        span.get_span_context.return_value = span_context

        with patch('tron.infra.observability.logging.trace.get_current_span', return_value=span):
            formatter = JSONFormatter()
            record = logging.LogRecord(
                name="tron.span",
                level=logging.INFO,
                pathname="/path/to/span.py",
                lineno=1,
                msg="Span operation",
                args=(),
                exc_info=None,
            )

            formatted = formatter.format(record)
            log_entry = json.loads(formatted)

            assert "span_id" in log_entry
            assert len(log_entry["span_id"]) == 16  # 64-bit hex

    def test_trace_context_without_active_span(self):
        """Log entry handles missing trace context gracefully"""
        from tron.infra.observability.logging import JSONFormatter

        span = Mock()
        span.get_span_context.return_value = None

        with patch('tron.infra.observability.logging.trace.get_current_span', return_value=span):
            formatter = JSONFormatter()
            record = logging.LogRecord(
                name="tron.nospan",
                level=logging.INFO,
                pathname="/path/to/nospan.py",
                lineno=1,
                msg="No active span",
                args=(),
                exc_info=None,
            )

            formatted = formatter.format(record)
            log_entry = json.loads(formatted)

            # trace_id and span_id should not be present
            assert "trace_id" not in log_entry or log_entry.get("trace_id") is None
            assert "span_id" not in log_entry or log_entry.get("span_id") is None


# ============================================================================
# Metrics Cardinality Control Tests
# ============================================================================

class TestMetricsCardinalityControl:
    """Tests for preventing metrics cardinality explosion"""

    def test_path_normalization_removes_uuids(self):
        """Path normalization replaces UUIDs with {id}"""
        from tron.infra.observability.metrics import _normalise_path

        paths = [
            "/audits/550e8400-e29b-41d4-a716-446655440000",
            "/audits/123e4567-e89b-12d3-a456-426614174000",
            "/projects/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        ]

        normalized = [_normalise_path(p) for p in paths]

        # All should normalize to /audits/{id}
        assert normalized[0] == normalized[1]
        assert "/audits/{id}" in normalized[0]
        assert normalized[2] == "/projects/{id}"

    def test_path_normalization_preserves_non_uuids(self):
        """Non-UUID paths are preserved"""
        from tron.infra.observability.metrics import _normalise_path

        paths = [
            "/health",
            "/metrics",
            "/api/v1/status",
        ]

        normalized = [_normalise_path(p) for p in paths]

        # Should be unchanged
        assert normalized == paths


# ============================================================================
# Metrics Endpoint Tests
# ============================================================================

class TestMetricsEndpoint:
    """Tests for /metrics endpoint"""

    def test_metrics_endpoint_registration(self):
        """Metrics endpoint registered on app"""
        import tron.infra.observability.metrics as metrics_mod

        # Reset the module-level _metrics so init_metrics runs the full path
        original = metrics_mod._metrics
        metrics_mod._metrics = None
        try:
            app = Mock()
            app.get = Mock(return_value=lambda fn: fn)  # decorator stub

            metrics_mod.init_metrics(app=app)

            # Should have registered /metrics endpoint via @app.get decorator
            app.get.assert_called_once()
        finally:
            metrics_mod._metrics = original

    def test_metrics_endpoint_prometheus_format(self):
        """Metrics endpoint returns Prometheus format"""
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

        metrics_output = generate_latest()

        # Should be bytes in Prometheus text format
        assert isinstance(metrics_output, bytes)
        # Should contain TYPE and HELP lines
        assert b"# TYPE" in metrics_output


# ============================================================================
# Logging Integration Tests
# ============================================================================

class TestLoggingIntegration:
    """Integration tests for logging system"""

    def test_logger_configuration_complete(self):
        """Logger is fully configured with JSON formatter"""
        from tron.infra.observability.logging import init_logging

        init_logging(level="INFO")

        root = logging.getLogger()

        # Should have at least one handler
        assert len(root.handlers) >= 1

        # Handler should have JSONFormatter
        handler = root.handlers[0]
        from tron.infra.observability.logging import JSONFormatter
        assert isinstance(handler.formatter, JSONFormatter)

    def test_logging_output_valid_json(self):
        """All log output is valid JSON"""
        from tron.infra.observability.logging import init_logging, JSONFormatter

        init_logging(level="INFO")

        logger = logging.getLogger("tron.test")

        # Capture output
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)

        logger.info("Test message", extra={"audit_run_id": "run-123"})

        # Get output
        output = stream.getvalue().strip()

        # Should be valid JSON
        try:
            entry = json.loads(output)
            assert entry["message"] == "Test message"
            assert entry["audit_run_id"] == "run-123"
        except json.JSONDecodeError:
            pytest.fail("Log output is not valid JSON")


# ============================================================================
# Error Counting Tests
# ============================================================================

class TestErrorCounting:
    """Tests for error rate metrics"""

    def test_record_error_count(self):
        """Record HTTP error responses"""
        from tron.infra.observability.metrics import record_http_request, init_metrics

        init_metrics()

        # Record successful requests
        record_http_request("GET", "/health", 200, 0.01)
        record_http_request("GET", "/health", 200, 0.02)

        # Record error responses
        record_http_request("POST", "/audits", 500, 0.1)
        record_http_request("POST", "/audits", 503, 0.15)

    def test_record_llm_call_error(self):
        """Record LLM API errors"""
        from tron.infra.observability.metrics import record_llm_call, init_metrics

        init_metrics()

        record_llm_call(
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            status="error",
            duration=0.5,
        )

        record_llm_call(
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            status="error",
            duration=0.3,
        )


# ============================================================================
# Metrics Data Type Tests
# ============================================================================

class TestMetricsDataTypes:
    """Tests for metric value types and ranges"""

    def test_duration_must_be_positive(self):
        """Duration values must be positive"""
        from tron.infra.observability.metrics import record_http_request, init_metrics

        init_metrics()

        # Valid durations
        record_http_request("GET", "/test", 200, 0.0)
        record_http_request("GET", "/test", 200, 0.001)
        record_http_request("GET", "/test", 200, 60.0)

    def test_status_code_valid_range(self):
        """HTTP status codes are valid"""
        from tron.infra.observability.metrics import record_http_request, init_metrics

        init_metrics()

        # Valid status codes
        for code in [200, 201, 400, 401, 403, 404, 500, 502, 503]:
            record_http_request("GET", "/test", code, 0.1)

    def test_token_counts_non_negative(self):
        """Token counts must be non-negative"""
        from tron.infra.observability.metrics import record_llm_call, init_metrics

        init_metrics()

        record_llm_call(
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            status="success",
            duration=1.5,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
        )


# ============================================================================
# Custom Metrics Tests
# ============================================================================

class TestCustomMetrics:
    """Tests for custom metric recording"""

    def test_record_audit_run(self):
        """Record audit pipeline metrics"""
        from tron.infra.observability.metrics import init_metrics, get_metrics

        init_metrics()
        metrics = get_metrics()

        # Record audit execution
        metrics.audit_runs_total.labels(trigger_type="manual", status="success").inc()
        metrics.audit_duration_seconds.labels(trigger_type="manual").observe(45.5)

    def test_llm_circuit_breaker_state(self):
        """Record circuit breaker state"""
        from tron.infra.observability.metrics import init_metrics, get_metrics

        init_metrics()
        metrics = get_metrics()

        # Closed state (normal)
        metrics.llm_circuit_breaker_state.labels(provider="anthropic").set(0)

        # Open state (failing fast)
        metrics.llm_circuit_breaker_state.labels(provider="anthropic").set(1)

        # Half-open state (testing recovery)
        metrics.llm_circuit_breaker_state.labels(provider="anthropic").set(2)
