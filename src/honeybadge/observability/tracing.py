"""OpenTelemetry tracing integration for HoneyBadge.

Provides W3C Trace Context-compliant distributed tracing that replaces the
custom ``TRC-YYYYMMDD-...`` trace_id format. When OpenTelemetry is configured
(via ``OTEL_EXPORTER_OTLP_ENDPOINT``), spans are exported to Jaeger/Tempo.
When not configured, tracing degrades to no-op (no overhead).

Usage in application code::

    from honeybadge.observability.tracing import tracer

    with tracer.start_as_current_span("process_query") as span:
        span.set_attribute("user_id", user_id)
        span.set_attribute("question_length", len(question))
        ...

This module also bridges OpenTelemetry trace IDs into structlog context so
that structured logs carry the same trace ID as distributed traces, enabling
Grafana's tracesToLogs navigation.
"""

from __future__ import annotations

import os
from typing import Any

import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Tracer initialization
# ---------------------------------------------------------------------------

_tracer: Any = None
_otel_enabled: bool = False


def init_tracing(service_name: str = "honeybadge-server") -> Any:
    """Initialize OpenTelemetry tracing.

    Configures OTLP export to the endpoint specified by
    ``OTEL_EXPORTER_OTLP_ENDPOINT`` (e.g. ``http://jaeger:4317``).
    When the environment variable is not set, tracing is disabled and
    ``start_as_current_span`` calls become no-ops.

    Args:
        service_name: The service name reported to the tracing backend.

    Returns:
        A tracer instance (real or no-op).
    """
    global _tracer, _otel_enabled

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        logger.info("otel_tracing_disabled", reason="OTEL_EXPORTER_OTLP_ENDPOINT not set")
        from opentelemetry import trace

        _tracer = trace.get_tracer(service_name)
        return _tracer

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({
            "service.name": service_name,
            "service.version": os.environ.get("OTEL_SERVICE_VERSION", "unknown"),
            "deployment.environment": os.environ.get("ENV", "development"),
        })

        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        _tracer = trace.get_tracer(service_name)
        _otel_enabled = True
        logger.info("otel_tracing_enabled", endpoint=endpoint, service=service_name)
        return _tracer

    except ImportError:
        logger.warning("otel_packages_not_installed", fallback="no-op tracer")
        from opentelemetry import trace

        _tracer = trace.get_tracer(service_name)
        return _tracer
    except Exception as e:
        logger.warning("otel_init_failed", error=str(e), fallback="no-op tracer")
        from opentelemetry import trace

        _tracer = trace.get_tracer(service_name)
        return _tracer


def get_tracer() -> Any:
    """Return the initialized tracer, initializing lazily if needed."""
    global _tracer
    if _tracer is None:
        init_tracing()
    return _tracer


def is_otel_enabled() -> bool:
    """Return True if OpenTelemetry export is active."""
    return _otel_enabled


# ---------------------------------------------------------------------------
# Structlog trace context bridge
# ---------------------------------------------------------------------------

def inject_trace_context_into_logs() -> None:
    """Configure structlog to include OTel trace/span IDs in log output.

    Must be called once at application startup (before any request processing).
    Adds ``trace_id`` and ``span_id`` fields to every log entry when a span
    is active, bridging the gap between distributed traces and structured logs.
    """
    try:
        from opentelemetry import trace
        from opentelemetry.trace import format_span_id, format_trace_id

        class _TraceIdProcessor:
            """structlog processor that injects OTel trace context."""

            def __call__(self, logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
                span = trace.get_current_span()
                if span and span.is_recording():
                    ctx = span.get_span_context()
                    if ctx and ctx.trace_id:
                        event_dict["trace_id"] = format_trace_id(ctx.trace_id)
                        event_dict["span_id"] = format_span_id(ctx.span_id)
                return event_dict

        # Register the processor with structlog
        structlog.configure(
            processors=[
                structlog.stdlib.add_log_level,
                _TraceIdProcessor(),  # type: ignore[list-item]
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            logger_factory=structlog.stdlib.LoggerFactory(),
        )
        logger.info("structlog_otel_bridge_configured")
    except ImportError:
        logger.info("otel_not_available_structlog_bridge_skipped")
    except Exception as e:
        logger.warning("structlog_otel_bridge_failed", error=str(e))
