"""Best-effort diagnostics independent of offset acknowledgement."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib import import_module
from threading import Condition, Thread
from uuid import uuid4

from sqlalchemy import delete, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from fleetmind.telemetry.broker import kafka, report
from fleetmind.telemetry.contracts import DeadLetter
from fleetmind.telemetry.live_models import (
    MetricSample,
    MetricTotals,
    ReportedDeadLetter,
    WorkerCheckpoint,
)

METRICS_PERIOD = 5
RETENTION = timedelta(days=1)
TIMINGS = ("inference_ms", "database_ms", "observation_to_commit_ms")


@dataclass(frozen=True)
class DiagnosticSnapshot:
    sampled_at: datetime
    running: bool
    lag: int | None
    counts: dict[str, int]
    timings: dict[str, tuple[int, float]]
    letters: tuple[DeadLetter, ...]


def save_snapshot(factory, worker_id, snapshot, broker_ok):
    with factory.begin() as db:
        # Serializes the totals update and makes retry of one checkpoint idempotent.
        totals = db.get_one(MetricTotals, 1, with_for_update=True)
        prior = db.get(WorkerCheckpoint, worker_id)
        if prior is not None and prior.sampled_at >= snapshot.sampled_at:
            return
        previous_counts = prior.counts if prior else {}
        previous_times = prior.timings if prior else {}
        delta = {
            key: value - previous_counts.get(key, 0)
            for key, value in snapshot.counts.items()
        }
        timing_delta = {}
        for key, (count, total) in snapshot.timings.items():
            prev_count, prev_total = previous_times.get(key, (0, 0))
            timing_delta[key] = (count - prev_count, total - prev_total)
        totals.counts = {
            key: totals.counts.get(key, 0) + value for key, value in delta.items()
        }
        if prior is None:
            prior = WorkerCheckpoint(worker_id=worker_id)
            db.add(prior)
        prior.sampled_at = snapshot.sampled_at
        prior.running = snapshot.running
        prior.broker_ok = broker_ok
        prior.lag = snapshot.lag
        prior.counts = snapshot.counts
        prior.timings = snapshot.timings
        db.add(
            MetricSample(
                sampled_at=snapshot.sampled_at,
                lag=snapshot.lag,
                counts=delta,
                timings=timing_delta,
            )
        )
        if snapshot.letters:
            db.execute(
                insert(ReportedDeadLetter)
                .values(
                    [
                        {
                            "topic": letter.original_topic,
                            "partition": letter.original_partition,
                            "offset": letter.original_offset,
                            "category": letter.category,
                            "rejected_at": letter.rejected_at,
                            "event_id": letter.event_id,
                        }
                        for letter in snapshot.letters
                    ]
                )
                .on_conflict_do_nothing()
            )
        cutoff = datetime.now(UTC) - RETENTION
        expired = (
            select(MetricSample.id)
            .where(MetricSample.sampled_at < cutoff)
            .order_by(
                MetricSample.sampled_at,
            )
            .limit(256)
        )
        db.execute(delete(MetricSample).where(MetricSample.id.in_(expired)))
        keys = (
            ReportedDeadLetter.topic,
            ReportedDeadLetter.partition,
            ReportedDeadLetter.offset,
        )
        expired_letters = (
            select(*keys)
            .where(ReportedDeadLetter.rejected_at < cutoff)
            .order_by(
                ReportedDeadLetter.rejected_at,
            )
            .limit(256)
        )
        db.execute(delete(ReportedDeadLetter).where(tuple_(*keys).in_(expired_letters)))


class WorkerReporter:
    """One replaceable snapshot and an independent DB connection pool."""

    def __init__(self, factory, bootstrap, topic):
        self.factory = factory
        self.worker_id = uuid4()
        self.topic = topic
        self.admin = import_module("confluent_kafka.admin").AdminClient(
            {"bootstrap.servers": bootstrap, "allow.auto.create.topics": False},
        )
        self.kafka_error = kafka().KafkaException
        self.condition = Condition()
        self.pending = None
        self.closed = False
        self.thread = Thread(target=self._run, daemon=True, name="telemetry-metrics")
        self.thread.start()

    def submit(self, snapshot):
        with self.condition:
            self.pending = snapshot
            self.condition.notify()

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify()
        self.thread.join(timeout=3)

    def _run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.pending is not None or self.closed)
                snapshot, self.pending = self.pending, None
                if snapshot is None:
                    return
            try:
                # A metadata response demonstrates broker reachability even if
                # this worker has no assigned partitions or no recent readings.
                broker_ok = bool(
                    self.admin.list_topics(topic=self.topic, timeout=1).brokers
                )
            except self.kafka_error:
                broker_ok = False
            try:
                save_snapshot(self.factory, self.worker_id, snapshot, broker_ok)
            except SQLAlchemyError:
                report("metrics_storage_unavailable")
