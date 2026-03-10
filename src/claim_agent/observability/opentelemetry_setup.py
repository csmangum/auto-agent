"""OpenTelemetry tracing setup alongside LangSmith.

When OTEL_TRACING=true, configures OTLP exporter for traces. Works in parallel
with LangSmith - both can be enabled for different backends.
"""

import logging
from typing import Any

from claim_agent.config import get_settings

logger = logging.getLogger(__name__)


def setup_opentelemetry() -> bool:
    """Set up OpenTelemetry tracing with OTLP exporter.

    Returns True if OpenTelemetry was successfully configured.
    """
    config = get_settings().tracing
    if not config.otel_enabled:
        logger.debug("OpenTelemetry tracing is disabled")
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as e:
        logger.warning(
            "OpenTelemetry packages not installed. Install with: pip install -e '.[opentelemetry]'. %s",
            e,
        )
        return False

    resource = Resource.create({
        "service.name": config.otel_service_name,
    })
    provider = TracerProvider(resource=resource)
    endpoint = config.otel_exporter_otlp_endpoint.rstrip("/")
    if not endpoint.startswith(("http://", "https://")):
        endpoint = f"http://{endpoint}"
    exporter = OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    logger.info(
        "OpenTelemetry tracing enabled (service=%s, endpoint=%s)",
        config.otel_service_name,
        config.otel_exporter_otlp_endpoint,
    )
    return True


def instrument_fastapi(app: Any) -> None:
    """Instrument FastAPI app with OpenTelemetry. Call only when setup_opentelemetry() returned True."""
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
        logger.debug("FastAPI instrumented with OpenTelemetry")
    except ImportError:
        logger.debug("opentelemetry-instrumentation-fastapi not installed, skipping FastAPI instrumentation")
