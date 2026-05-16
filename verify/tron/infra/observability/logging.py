"""
Structured JSON logging with trace correlation.

Emits logs as JSON lines so Loki can parse fields natively.
Every log entry includes trace_id and span_id from the active
OpenTelemetry context, enabling Grafana trace ↔ log linking.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any, Dict

from opentelemetry import trace

from tron.api.config import settings


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON with trace context."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "timestamp": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": settings.service_name,
        }

        # Trace correlation
        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx and ctx.trace_id:
            log_entry["trace_id"] = format(ctx.trace_id, "032x")
            log_entry["span_id"] = format(ctx.span_id, "016x")

        # Extra fields set via logger.info("msg", extra={...})
        for key in ("audit_run_id", "project_id", "agent_id", "request_id",
                     "method", "path", "status_code", "duration_ms",
                     "provider", "model", "tokens", "cost_usd"):
            val = getattr(record, key, None)
            if val is not None:
                log_entry[key] = val

        # Exception info
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
            }
            log_entry["traceback"] = self.formatException(record.exc_info)

        # Source location (for debug-level detail)
        if record.levelno <= logging.DEBUG:
            log_entry["source"] = {
                "file": record.pathname,
                "line": record.lineno,
                "function": record.funcName,
            }

        return json.dumps(log_entry, default=str)

    def formatTime(self, record, datefmt=None):
        """ISO-8601 with milliseconds."""
        import datetime
        dt = datetime.datetime.fromtimestamp(record.created, tz=datetime.timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(record.msecs):03d}Z"


def init_logging(level: str | None = None) -> None:
    """Configure root logger with JSON output.

    Call once at startup. Replaces any existing handlers on the root
    logger with a single JSON-formatted stderr handler.
    """
    log_level = getattr(logging, (level or settings.log_level).upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(log_level)

    # Remove existing handlers to avoid duplicate output
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JSONFormatter())
    root.addHandler(handler)

    # Silence noisy third-party loggers
    for name in ("uvicorn.access", "opentelemetry", "httpcore", "hpack"):
        logging.getLogger(name).setLevel(logging.WARNING)

    logging.getLogger(__name__).info("Structured JSON logging initialised")
