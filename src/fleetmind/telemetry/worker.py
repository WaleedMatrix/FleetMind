"""Sequential Kafka consumption with commit-after-durability semantics."""

import math
from collections import Counter, deque
from datetime import UTC, datetime
from threading import Event
from time import monotonic, perf_counter

from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError, OperationalError

from fleetmind.observability import (
    CORRELATION,
    DURATION,
    EVENTS,
    LAG,
    REJECTIONS,
    WORKER,
    correlation,
    timed,
)
from fleetmind.services.predictions import AssetValidationError
from fleetmind.telemetry.broker import BrokerFailure, BrokerSettings, Publisher, report
from fleetmind.telemetry.contracts import MAX_EVENT_BYTES, DeadLetter, TelemetryEvent
from fleetmind.telemetry.reporting import METRICS_PERIOD, TIMINGS, DiagnosticSnapshot
from fleetmind.telemetry.storage import EventRejected


class WorkerHalt(RuntimeError):
    """Stop this consumer before an unhandled offset can be passed."""


def timestamp():
    return datetime.now(UTC)


def decode(message) -> TelemetryEvent:
    body = message.value()
    if not body or len(body) > MAX_EVENT_BYTES:
        raise EventRejected("invalid_payload")
    try:
        event = TelemetryEvent.model_validate_json(body)
    except ValidationError as exc:
        if any(
            error["loc"] == ("schema_version",) and error["type"] != "missing"
            for error in exc.errors(include_input=False)
        ):
            raise EventRejected("unsupported_version") from None
        raise EventRejected("invalid_payload") from None
    if message.key() != event.asset_id.encode("ascii"):
        raise EventRejected("partition_key_mismatch")
    return event


def is_transient(error: DBAPIError):
    code = getattr(error.orig, "sqlstate", None)
    if code:
        return code.startswith(("08", "40", "53", "57")) or code == "55P03"
    return error.connection_invalidated or isinstance(error, OperationalError)


def latency_summary(values):
    if not values:
        return None
    ordered = sorted(values)
    result = {"samples": len(ordered)}
    for rank in (50, 95, 99):
        index = math.ceil(len(ordered) * rank / 100) - 1
        result[f"p{rank}"] = round(ordered[index], 3)
    return result


class TelemetryWorker:
    def __init__(
        self,
        consumer,
        publisher: Publisher,
        store,
        settings: BrokerSettings,
        stop: Event,
        *,
        retries: int = 3,
        emit=report,
        trace: bool = False,
        read_lag=lambda: None,
        submit_metrics=None,
    ):
        self.consumer = consumer
        self.publisher = publisher
        self.store = store
        self.settings = settings
        self.stop = stop
        self.retries = retries
        self.emit = emit
        self.trace = trace
        self.read_lag = read_lag
        self.submit_metrics = submit_metrics
        self.timing_totals = {name: (0, 0.0) for name in TIMINGS}
        self.recent_letters = deque(maxlen=128)
        self.started = monotonic()
        self.counts = Counter(
            {
                name: 0
                for name in (
                    "received",
                    "processed",
                    "duplicates",
                    "invalid",
                    "retried_events",
                    "retry_attempts",
                    "dead_lettered",
                    "committed",
                )
            }
        )
        self.samples = {
            name: deque(maxlen=4096)
            for name in (
                "inference_ms",
                "database_ms",
                "observation_to_commit_ms",
                "processing_ms",
            )
        }

    def _persist(self, event, received_at):
        for attempt in range(self.retries + 1):
            if attempt:
                if self.stop.wait(min(2 ** (attempt - 1) / 4, 2)):
                    raise WorkerHalt("Shutdown interrupted database retry.")
                self.counts["retry_attempts"] += 1
                EVENTS.labels("retry_attempts").inc()
                if attempt == 1:
                    self.counts["retried_events"] += 1
            try:
                return self.store.persist(event, received_at)
            except DBAPIError as exc:
                if not is_transient(exc):
                    raise WorkerHalt("Database operation failed permanently.") from None
                if attempt == self.retries:
                    raise WorkerHalt(
                        "Database retries exhausted; offset left pending."
                    ) from None
                self.emit("database_retry", attempt=attempt + 1)
        raise AssertionError("Retry loop did not terminate.")

    def _dead_letter(self, message, category, event):
        letter = DeadLetter(
            category=category,
            rejected_at=timestamp(),
            original_topic=message.topic(),
            original_partition=message.partition(),
            original_offset=message.offset(),
            event_id=event.event_id if event else None,
        )
        key = (
            f"{letter.original_topic}:{letter.original_partition}:"
            f"{letter.original_offset}"
        )
        self.publisher.publish(
            self.settings.dead_letter_topic, key, letter.model_dump_json().encode()
        )
        self.counts["dead_lettered"] += 1
        EVENTS.labels("dead_lettered").inc()
        self.recent_letters.append(letter)
        self.emit("dead_lettered", **letter.model_dump(mode="json"))

    def process(self, message):
        """Handle one offset synchronously; exceptions stop the outer loop."""
        with correlation(), timed("telemetry_delivery"):
            self._process(message)

    def _process(self, message):
        received_at = timestamp()
        started = perf_counter()
        self.counts["received"] += 1
        EVENTS.labels("received").inc()
        event = None
        timings = {}
        try:
            with timed("telemetry_decode"):
                event = decode(message)
            CORRELATION.set(event.event_id.hex)
            outcome = self._persist(event, received_at)
        except (EventRejected, AssetValidationError) as exc:
            self.counts["invalid"] += 1
            EVENTS.labels("invalid").inc()
            REJECTIONS.labels(exc.category).inc()
            self._dead_letter(message, exc.category, event)
            status = "invalid"
        else:
            status = "duplicates" if outcome.duplicate else "processed"
            self.counts[status] += 1
            EVENTS.labels(status).inc()
            if not outcome.duplicate:
                DURATION.labels("telemetry_database", "ok").observe(
                    outcome.database_ms / 1000
                )
                timings = {
                    "inference_ms": outcome.inference_ms,
                    "database_ms": outcome.database_ms,
                    "observation_to_commit_ms": (
                        timestamp() - event.observed_at
                    ).total_seconds()
                    * 1000,
                }
        for name, value in timings.items():
            count, total = self.timing_totals[name]
            self.timing_totals[name] = (count + 1, total + value)
        with timed("offset_acknowledgement"):
            committed = self.consumer.commit(message=message, asynchronous=False)
            if not committed or any(
                partition.error is not None for partition in committed
            ):
                raise WorkerHalt(
                    "Offset acknowledgement failed. Restart at the committed position."
                )
        self.counts["committed"] += 1
        EVENTS.labels("committed").inc()
        timings["processing_ms"] = (perf_counter() - started) * 1000
        for name, value in timings.items():
            self.samples[name].append(value)
        if self.trace:
            self.emit(
                "event_handled",
                outcome=status,
                event_id=str(event.event_id) if event else None,
                partition=message.partition(),
                offset=message.offset(),
                handled_monotonic_s=monotonic(),
                **timings,
            )

    def snapshot(self):
        return {
            **self.counts,
            "elapsed_s": round(monotonic() - self.started, 3),
            "assigned_committed_lag": self.read_lag(),
            "latency": {
                name: latency_summary(values) for name, values in self.samples.items()
            },
        }

    def _export(self, running):
        lag = self.read_lag()
        LAG.set(math.nan if lag is None or not running else lag)
        if self.submit_metrics is not None:
            self.submit_metrics(
                DiagnosticSnapshot(
                    sampled_at=timestamp(),
                    running=running,
                    lag=lag,
                    counts=dict(self.counts),
                    timings=dict(self.timing_totals),
                    letters=tuple(self.recent_letters),
                )
            )

    def run(self, max_events: int | None = None, report_interval: float = 5):
        next_report = monotonic() + report_interval
        next_export = monotonic() + METRICS_PERIOD
        WORKER.set(1)
        self._export(True)
        try:
            while not self.stop.is_set():
                with timed("kafka_poll"):
                    message = self.consumer.poll(0.25)
                if self.stop.is_set():
                    break
                if message is not None:
                    error = message.error()
                    if error is None:
                        self.process(message)
                    elif error.fatal() or not error.retriable():
                        raise BrokerFailure(f"Consumer error: {error.name()}.")
                    else:
                        self.emit("consumer_retry", code=error.name())
                if monotonic() >= next_report:
                    self.emit("worker_metrics", **self.snapshot())
                    next_report = monotonic() + report_interval
                if monotonic() >= next_export:
                    self._export(True)
                    next_export = monotonic() + METRICS_PERIOD
                if max_events is not None and self.counts["committed"] >= max_events:
                    break
        finally:
            WORKER.set(0)
            self._export(False)
            self.emit("worker_stopped", **self.snapshot())
            self.consumer.close()
