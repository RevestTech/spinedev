"""
OpenTelemetry distributed tracing.

Sets up TracerProvider with OTLP exporter → otel-collector → Tempo.
Auto-instruments FastAPI, SQLAlchemy, Redis, and httpx.

Trace context propagates through:
  API request → DB queries → Redis commands → LLM HTTP calls → Temporal activities
"""

from __future__ import annotations

import logging
from typing import Optional

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.trace import StatusCode

from tron.api.config import settings

logger = logging.getLogger(__name__)

_provider: Optional[TracerProvider] = None


def init_tracing(app=None) -> None:
    """Initialise the TracerProvider and auto-instrument libraries.

    Args:
        app: FastAPI app instance for FastAPI auto-instrumentation.
    """
    global _provider

    resource = Resource.create({
        "service.name": settings.service_name,
        "service.version": "5.1.0",
        "deployment.environment": "development",
    })

    _provider = TracerProvider(resource=resource)

    # OTLP exporter → otel-collector
    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )

        exporter = OTLPSpanExporter(endpoint=settings.otel_endpoint, insecure=True)
        _provider.add_span_processor(BatchSpanProcessor(exporter))
        logger.info("OTLP trace exporter configured → %s", settings.otel_endpoint)
    except ImportError:
        logger.warning(
            "opentelemetry-exporter-otlp-proto-grpc not installed; "
            "traces will be recorded in-process only"
        )
    except Exception as exc:
        logger.warning("Failed to configure OTLP exporter: %s", exc)

    trace.set_tracer_provider(_provider)

    # ── Auto-instrument libraries ──

    # FastAPI
    if app is not None:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor.instrument_app(
                app,
                excluded_urls="health,ready,metrics",
            )
            logger.info("FastAPI auto-instrumentation enabled")
        except ImportError:
            logger.warning("opentelemetry-instrumentation-fastapi not installed")
        except RuntimeError:
            logger.warning(
                "Cannot add FastAPI instrumentation middleware after startup; "
                "skipping (traces from other libraries still active)"
            )

    # SQLAlchemy
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        SQLAlchemyInstrumentor().instrument(enable_commenter=True)
        logger.info("SQLAlchemy auto-instrumentation enabled")
    except ImportError:
        pass  # optional

    # Redis
    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor

        RedisInstrumentor().instrument()
        logger.info("Redis auto-instrumentation enabled")
    except ImportError:
        pass  # optional

    # httpx (used by LLMClient)
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
        logger.info("httpx auto-instrumentation enabled")
    except ImportError:
        pass  # optional

    logger.info("Tracing initialised (service=%s)", settings.service_name)


def shutdown_tracing() -> None:
    """Flush pending spans and shut down the provider."""
    global _provider
    if _provider:
        _provider.shutdown()
        _provider = None
        logger.info("Tracing shut down")


def get_tracer(name: str = "tron") -> trace.Tracer:
    """Return a named tracer for manual span creation."""
    return trace.get_tracer(name)


def record_exception(span: trace.Span, exc: Exception) -> None:
    """Record an exception on a span and set ERROR status."""
    span.set_status(StatusCode.ERROR, str(exc))
    span.record_exception(exc)
