"""Bounded queries for reported telemetry health and rolling samples."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from fleetmind.telemetry.contracts import DeadLetter
from fleetmind.telemetry.live import high_watermark, storage_state
from fleetmind.telemetry.live_models import (
    MetricSample,
    MetricTotals,
    ReportedDeadLetter,
    WorkerCheckpoint,
)
from fleetmind.telemetry.live_schemas import (
    Counters,
    DeadLetterSnapshot,
    MetricPoint,
    MonitoringMetrics,
)
from fleetmind.telemetry.reporting import TIMINGS
from fleetmind.telemetry.storage import TelemetryAssessment

WINDOW = 300
BUCKET = 10
FRESHNESS = 20
SAMPLE_LIMIT = 3600
WORKER_LIMIT = 64


def bucketed(samples, now):
    bins = defaultdict(list)
    for row in samples:
        bins[int(row.sampled_at.timestamp()) // BUCKET * BUCKET].append(row)
    latest = int(now.timestamp()) // BUCKET * BUCKET
    points = []
    for start in range(latest - WINDOW + BUCKET, latest + 1, BUCKET):
        rows = bins[start]
        point = MetricPoint(started_at=datetime.fromtimestamp(start, UTC))
        if rows:
            # Normalize by the fixed reporting bucket, including the current bucket.
            point.received_per_s = sum(row.counts["received"] for row in rows) / BUCKET
            point.committed_per_s = (
                sum(row.counts["committed"] for row in rows) / BUCKET
            )
            point.max_worker_lag = max(
                (row.lag for row in rows if row.lag is not None), default=None
            )
            for name in TIMINGS:
                pairs = [row.timings.get(name, (0, 0)) for row in rows]
                count = sum(pair[0] for pair in pairs)
                if count:
                    setattr(point, name, sum(pair[1] for pair in pairs) / count)
        points.append(point)
    return points


def metrics(db, now=None):
    now = now or datetime.now(UTC)
    try:
        high = high_watermark(db)
        totals = db.get_one(MetricTotals, 1).counts
        workers = list(
            db.scalars(
                select(WorkerCheckpoint)
                .order_by(
                    WorkerCheckpoint.sampled_at.desc(),
                )
                .limit(WORKER_LIMIT + 1)
            )
        )
        samples = list(
            db.scalars(
                select(MetricSample)
                .where(
                    MetricSample.sampled_at >= now - timedelta(seconds=WINDOW),
                )
                .order_by(MetricSample.sampled_at.desc())
                .limit(SAMPLE_LIMIT + 1)
            )
        )
        assessed = db.scalar(
            select(TelemetryAssessment.assessed_at)
            .order_by(TelemetryAssessment.assessed_at.desc())
            .limit(1)
        )
    except SQLAlchemyError as exc:
        return MonitoringMetrics(state=storage_state(exc), as_of=now)
    clipped = len(workers) > WORKER_LIMIT or len(samples) > SAMPLE_LIMIT
    fresh = [
        row
        for row in workers[:WORKER_LIMIT]
        if row.sampled_at >= now - timedelta(seconds=FRESHNESS)
    ]
    active = [row for row in fresh if row.running]
    known_probes = [row for row in workers if row.broker_ok is not None]
    probes = [row.broker_ok for row in fresh if row.broker_ok is not None]
    worker = (
        "available"
        if active
        else "stopped"
        if fresh
        else "stale"
        if workers
        else "unknown"
    )
    broker = (
        "available"
        if any(probes)
        else "unavailable"
        if probes
        else "stale"
        if known_probes
        else "unknown"
    )
    return MonitoringMetrics(
        state="ready",
        as_of=now,
        window_seconds=WINDOW,
        bucket_seconds=BUCKET,
        stale_after_seconds=FRESHNESS,
        worker=worker,
        broker=broker,
        active_workers=len(active) if fresh and not clipped else None,
        last_report_at=workers[0].sampled_at if workers else None,
        last_broker_probe_at=known_probes[0].sampled_at if known_probes else None,
        durable_assessments=high,
        last_assessed_at=assessed,
        reported_totals=Counters(**totals) if totals else None,
        max_worker_lag=max(
            (row.lag for row in active if row.lag is not None), default=None
        ),
        truncated=clipped,
        points=bucketed(samples[:SAMPLE_LIMIT], now),
    )


def dead_letters(db, limit):
    try:
        last = db.scalar(
            select(WorkerCheckpoint.sampled_at)
            .order_by(
                WorkerCheckpoint.sampled_at.desc(),
            )
            .limit(1)
        )
        rows = list(
            db.scalars(
                select(ReportedDeadLetter)
                .where(
                    ReportedDeadLetter.rejected_at
                    >= datetime.now(UTC) - timedelta(days=1),
                )
                .order_by(ReportedDeadLetter.rejected_at.desc())
                .limit(limit)
            )
        )
    except SQLAlchemyError as exc:
        return DeadLetterSnapshot(state=storage_state(exc))
    return DeadLetterSnapshot(
        state="ready",
        last_report_at=last,
        items=[
            DeadLetter(
                category=row.category,
                event_id=row.event_id,
                rejected_at=row.rejected_at,
                original_topic=row.topic,
                original_partition=row.partition,
                original_offset=row.offset,
            )
            for row in rows
        ],
    )
