"""OpenTelemetry setup: traces, metrics and logs exported over OTLP/HTTP.

The exporter endpoint and resource attributes come from the standard OTEL_* environment
variables (OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_RESOURCE_ATTRIBUTES). SERVICE_VERSION sets
service.version.
"""

import json
import logging
import os
import sys

from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_configured = False


class JsonFormatter(logging.Formatter):
    """One JSON object per line on stdout, with the active trace and span ids."""

    def format(self, record: logging.LogRecord) -> str:
        span = trace.get_current_span().get_span_context()
        entry: dict[str, object] = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        if span.is_valid:
            entry["trace_id"] = format(span.trace_id, "032x")
            entry["span_id"] = format(span.span_id, "016x")
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def setup(service_name: str) -> None:
    """Configure providers and exporters once per process."""
    global _configured
    if _configured:
        return
    _configured = True

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": os.environ.get("SERVICE_VERSION", "0.0.0"),
        }
    )
    export = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") is not None

    tracer_provider = TracerProvider(resource=resource)
    if export:
        tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    readers = [PeriodicExportingMetricReader(OTLPMetricExporter())] if export else []
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=readers))

    logger_provider = LoggerProvider(resource=resource)
    if export:
        logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    set_logger_provider(logger_provider)

    stdout = logging.StreamHandler(sys.stdout)
    stdout.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [stdout, LoggingHandler(logger_provider=logger_provider)]
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    for noisy in ("httpx", "httpcore", "uvicorn.access", "aiormq", "aio_pika"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    HTTPXClientInstrumentor().instrument()
