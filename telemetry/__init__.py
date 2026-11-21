"""OpenTelemetry for every service: logs, metrics and traces over OTLP.

    telemetry.setup("core")      # after logging.basicConfig, in each service's main

Locally the endpoint is the Grafana LGTM container (docker-compose `telemetry`: Grafana at http://localhost:3000).
Moving to a hosted backend later is configuration only: point OTEL_EXPORTER_OTLP_ENDPOINT (and
OTEL_EXPORTER_OTLP_HEADERS for its key) somewhere else. With no endpoint set, or the packages missing, it does
nothing and the service runs as before. The local log files stay either way.
"""
import logging
import os
import socket

log = logging.getLogger("telemetry")
_meter = None


def setup(service: str) -> bool:
    """Send this process's logs, metrics and traces to the OTLP endpoint. Returns whether it's on."""
    global _meter
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or os.environ.get("TELEMETRY", "1") == "0":
        return False
    try:
        from opentelemetry import metrics, trace
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as e:
        log.warning("telemetry off: %s (pip install -r requirements.txt)", e)
        return False
    resource = Resource.create({"service.name": service, "service.namespace": "home",
                                "host.name": socket.gethostname().split(".")[0],
                                "deployment.environment": os.environ.get("TELEMETRY_ENV", "home")})
    tracer = TracerProvider(resource=resource)
    tracer.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer)
    reader = PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=15_000)
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))
    logs = LoggerProvider(resource=resource)
    logs.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    set_logger_provider(logs)
    logging.getLogger().addHandler(LoggingHandler(level=logging.INFO, logger_provider=logs))
    for noisy in ("urllib3", "opentelemetry", "httpx", "httpcore"):  # the exporter's own chatter would loop back
        logging.getLogger(noisy).propagate = False
    _meter = metrics.get_meter(f"home.{service}")
    return True


def meter():
    """The service's meter (a no-op one when telemetry is off)."""
    if _meter is not None:
        return _meter
    from opentelemetry import metrics  # the API package is light and present whenever the SDK is
    return metrics.get_meter("home")


def gauge(name: str, callback, description: str = "", unit: str = ""):
    """An observable gauge read every export: `callback()` returns [(value, {attributes}), ...]."""
    try:
        from opentelemetry.metrics import Observation
    except ImportError:
        return
    meter().create_observable_gauge(name, callbacks=[lambda _opts: [Observation(v, a) for v, a in callback()]],
                                    description=description, unit=unit)
