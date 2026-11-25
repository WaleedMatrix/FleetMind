"""Bounded Prometheus metrics, correlation, and optional sampled OTLP traces."""

import json
import logging
import os
import re
from collections.abc import Callable
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from datetime import UTC, datetime
from math import nan
from pathlib import Path
from secrets import compare_digest
from threading import Thread
from time import perf_counter, process_time
from uuid import uuid4
from wsgiref.simple_server import WSGIRequestHandler, make_server

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    make_wsgi_app,
)
from prometheus_client.core import CounterMetricFamily
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import Response

REGISTRY = CollectorRegistry()
BUCKETS = (
    0.0005,
    0.001,
    0.0025,
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1,
    2.5,
    5,
    10,
    30,
    60,
)
HTTP = ("method", "route", "status")
REQUESTS = Counter(
    "fleetmind_http_requests", "Completed API requests", HTTP, registry=REGISTRY
)
HTTP_DURATION = Histogram(
    "fleetmind_http_request_duration_seconds",
    "API time through final response or disconnect",
    HTTP,
    buckets=(*BUCKETS, 120, 300),
    registry=REGISTRY,
)
DURATION = Histogram(
    "fleetmind_operation_duration_seconds",
    "Operation wall time",
    ("operation", "outcome"),
    buckets=BUCKETS,
    registry=REGISTRY,
)
EVENTS = Counter(
    "fleetmind_telemetry_events",
    "Worker deliveries by processing stage",
    ("stage",),
    registry=REGISTRY,
)
REJECTIONS = Counter(
    "fleetmind_telemetry_rejected",
    "Telemetry validation rejections by category",
    ("category",),
    registry=REGISTRY,
)
LAG = Gauge(
    "fleetmind_worker_committed_lag",
    "Offsets pending in currently assigned partitions",
    registry=REGISTRY,
)
LAG.set(nan)
WORKER = Gauge(
    "fleetmind_worker_running", "Worker consumption lifecycle", registry=REGISTRY
)
DEPENDENCY = Gauge(
    "fleetmind_dependency_available",
    "Latest local dependency check, NaN if unknown",
    ("dependency",),
    registry=REGISTRY,
)
SSE = Gauge(
    "fleetmind_sse_connections", "Active SSE responses", ("stream",), registry=REGISTRY
)
SSE_CLOSED = Counter(
    "fleetmind_sse_closed",
    "Closed SSE responses",
    ("stream", "outcome"),
    registry=REGISTRY,
)
COPILOT = Counter(
    "fleetmind_copilot_responses",
    "Completed Copilot orchestrations",
    ("provider", "status"),
    registry=REGISTRY,
)
PROVIDER_FAILURE = Counter(
    "fleetmind_copilot_provider_failures",
    "Reported provider failures",
    ("provider", "category"),
    registry=REGISTRY,
)
TOOLS = Histogram(
    "fleetmind_copilot_tool_duration_seconds",
    "Tool execution wall time",
    ("tool", "outcome"),
    buckets=BUCKETS,
    registry=REGISTRY,
)
TOKENS = Counter(
    "fleetmind_copilot_reported_tokens",
    "Provider-reported tokens including failed orchestrations",
    ("provider", "direction"),
    registry=REGISTRY,
)


class ProcessCPU:
    def collect(self):
        yield CounterMetricFamily(
            "fleetmind_process_cpu_seconds",
            "Process user and system CPU seconds",
            value=process_time(),
        )


REGISTRY.register(ProcessCPU())
try:
    import psutil
except ImportError:
    pass
else:
    PROCESS = psutil.Process()
    Gauge(
        "fleetmind_process_start_time_seconds",
        "Process start time as a Unix timestamp",
        registry=REGISTRY,
    ).set(PROCESS.create_time())
    Gauge(
        "fleetmind_process_resident_memory_bytes",
        "Process resident memory",
        registry=REGISTRY,
    ).set_function(lambda: PROCESS.memory_info().rss)

CORRELATION = ContextVar("fleetmind_correlation", default=None)
HEX_ID = re.compile(r"^[0-9a-f]{32}$")
logger = logging.getLogger("fleetmind.events")
tracer = None


def event(operation, *, outcome="ok", duration=None, category=None):
    """Emit allowlisted fields only. Callers pass static operations and categories."""
    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "operation": operation,
        "outcome": outcome,
        "correlation_id": CORRELATION.get(),
    }
    if duration is not None:
        payload["duration_ms"] = round(1000 * duration, 3)
    if category is not None:
        payload["category"] = category
    logger.info(json.dumps(payload, separators=(",", ":")))


@contextmanager
def correlation(identifier=None):
    token = CORRELATION.set(identifier or uuid4().hex)
    try:
        yield CORRELATION.get()
    finally:
        CORRELATION.reset(token)


def configure_logging():
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def configure_tracing(service):
    global tracer
    if not os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or tracer is not None:
        return None
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

        rate = float(os.getenv("FLEETMIND_TRACE_SAMPLE_RATE", "0.02"))
        if not 0 < rate <= 0.25:
            raise ValueError("Invalid trace sample rate")
        provider = TracerProvider(
            resource=Resource.create({"service.name": service}),
            sampler=TraceIdRatioBased(rate),
        )
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(timeout=3),
                max_queue_size=128,
                max_export_batch_size=32,
                schedule_delay_millis=2000,
                export_timeout_millis=3000,
            )
        )
    except (ImportError, ValueError):
        event("trace_configuration", outcome="unavailable")
        return None
    tracer = provider.get_tracer("fleetmind")
    return provider


def span(operation):
    if tracer is None:
        return nullcontext()
    return tracer.start_as_current_span(
        operation, record_exception=False, set_status_on_exception=False
    )


def stop_tracing(provider):
    global tracer
    if provider is not None:
        provider.shutdown()
        tracer = None


@contextmanager
def timed(operation, *, log=False):
    started = perf_counter()
    outcome = "ok"
    with span(operation):
        try:
            yield
        except BaseException:
            outcome = "error"
            raise
        finally:
            elapsed = perf_counter() - started
            DURATION.labels(operation, outcome).observe(elapsed)
            if log or outcome == "error":
                event(operation, outcome=outcome, duration=elapsed)


def metrics_token():
    path = os.getenv("FLEETMIND_METRICS_TOKEN_FILE")
    if not path:
        return None
    try:
        with Path(path).open(encoding="ascii") as stream:
            token = stream.read(129).strip()
    except (OSError, UnicodeError):
        return None
    return token if re.fullmatch(r"[A-Za-z0-9_-]{32,96}", token) else None


def metrics_allowed(value, token):
    expected = f"Bearer {token}"
    return bool(token and value and value.isascii() and compare_digest(value, expected))


def metrics_response(request: Request, probe: Callable[[], None]):
    if not metrics_allowed(request.headers.get("authorization"), metrics_token()):
        return Response(status_code=404, headers={"Cache-Control": "no-store"})
    probe()
    return Response(
        generate_latest(REGISTRY),
        headers={"Content-Type": CONTENT_TYPE_LATEST, "Cache-Control": "no-store"},
    )


class QuietScrape(WSGIRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *_args):
        pass


@contextmanager
def worker_scrape(port):
    if port is None:
        yield
        return
    if not metrics_token():
        raise ValueError("Worker metrics require a valid FLEETMIND_METRICS_TOKEN_FILE.")
    export = make_wsgi_app(registry=REGISTRY)

    def app(environ, start_response):
        if (
            environ["PATH_INFO"] == "/metrics"
            and environ["REQUEST_METHOD"] == "GET"
            and metrics_allowed(environ.get("HTTP_AUTHORIZATION"), metrics_token())
        ):
            return export(environ, start_response)
        start_response("404 Not Found", [("Content-Length", "0")])
        return [b""]

    with make_server("127.0.0.1", port, app, handler_class=QuietScrape) as server:
        worker = Thread(target=server.serve_forever, name="worker-metrics", daemon=True)
        worker.start()
        try:
            yield
        finally:
            server.shutdown()
            worker.join(timeout=2)


class RequestMetrics:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] == "/metrics":
            await self.app(scope, receive, send)
            return
        request_id = Headers(scope=scope).get("x-request-id", "")
        request_id = request_id if HEX_ID.fullmatch(request_id) else None
        method = scope["method"]
        if method not in {"GET", "POST", "PATCH", "PUT", "DELETE", "HEAD", "OPTIONS"}:
            method = "OTHER"
        started = perf_counter()
        status, stream, complete = None, None, False

        with correlation(request_id) as identifier, span("http_request"):

            async def wrapped(message):
                nonlocal status, stream, complete
                if message["type"] == "http.response.start":
                    status = message["status"]
                    headers = message.setdefault("headers", [])
                    headers.append((b"x-request-id", identifier.encode("ascii")))
                    if any(
                        key == b"content-type" and val.startswith(b"text/event-stream")
                        for key, val in headers
                    ):
                        stream = "copilot" if method == "POST" else "telemetry"
                        SSE.labels(stream).inc()
                await send(message)
                if message["type"] == "http.response.body" and not message.get(
                    "more_body"
                ):
                    complete = True

            try:
                await self.app(scope, receive, wrapped)
            except Exception:
                if status is None:
                    status = 500
                raise
            finally:
                # Only route templates assigned by FastAPI are used as labels.
                route = getattr(scope.get("route"), "path", "unmatched")
                if status is None:
                    status_label = "no_response"
                else:
                    status_label = str(status) if 100 <= status <= 599 else "other"
                elapsed = perf_counter() - started
                REQUESTS.labels(method, route, status_label).inc()
                HTTP_DURATION.labels(method, route, status_label).observe(elapsed)
                if stream:
                    SSE.labels(stream).dec()
                    SSE_CLOSED.labels(
                        stream, "ended" if complete else "interrupted"
                    ).inc()
                event(
                    "http_request",
                    outcome=status_label,
                    duration=elapsed,
                    category=route,
                )
