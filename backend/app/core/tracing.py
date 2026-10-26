"""Optional vendor-neutral tracing; never stores product data or provider payloads."""

import logging
import os
from functools import lru_cache

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult

logger = logging.getLogger(__name__)


class SafeExporter(SpanExporter):
    """Protect SDK callers, including shutdown, from transport exceptions."""

    def __init__(self, exporter: SpanExporter):
        self.exporter = exporter

    def export(self, spans):
        try:
            return self.exporter.export(spans)
        except Exception:
            logger.warning("Trace export unavailable")
            return SpanExportResult.FAILURE

    def shutdown(self):
        try:
            self.exporter.shutdown()
        except Exception:
            logger.warning("Trace exporter shutdown unavailable")


def create_provider() -> trace.TracerProvider:
    if os.getenv("OTEL_SDK_DISABLED", "false").lower() == "true":
        return trace.NoOpTracerProvider()
    try:
        # A private provider avoids interfering with Chroma or global auto-instrumentation.
        provider = TracerProvider(
            resource=Resource.create({"service.name": os.getenv("OTEL_SERVICE_NAME", "auron")})
        )
        exporter_name = os.getenv("OTEL_TRACES_EXPORTER", "none")
        if exporter_name == "otlp":
            protocol = os.getenv(
                "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL",
                os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc"),
            )
            if protocol != "grpc":
                raise ValueError("This deployment supports OTLP/gRPC")
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

            provider.add_span_processor(BatchSpanProcessor(SafeExporter(OTLPSpanExporter())))
        elif exporter_name != "none":
            raise ValueError("Unsupported trace exporter")
        return provider
    except Exception:
        logger.warning("Tracing configuration unavailable; tracing disabled")
        return trace.NoOpTracerProvider()


@lru_cache(maxsize=1)
def get_tracer() -> trace.Tracer:
    return create_provider().get_tracer("auron.competitive_intelligence", "2.0.0")


def safely(action, *args, **kwargs):
    """Only wrap observability operations, never the operation being observed."""
    try:
        return action(*args, **kwargs)
    except Exception:
        logger.warning("Trace instrumentation unavailable")
        return None
