"""Durable live feed and reported worker diagnostics."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from fleetmind.db.database import Base


class StreamCursor(Base):
    __tablename__ = "telemetry_stream_cursor"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    position: Mapped[int] = mapped_column(BigInteger)


class StreamRecord(Base):
    __tablename__ = "telemetry_stream_events"

    position: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=False
    )
    event_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("telemetry_assessments.event_id", name="fk_telemetry_stream_event"),
        unique=True,
    )


class WorkerCheckpoint(Base):
    __tablename__ = "telemetry_worker_checkpoints"
    __table_args__ = (Index("ix_telemetry_workers_sampled", "sampled_at"),)

    worker_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    running: Mapped[bool]
    broker_ok: Mapped[bool | None]
    lag: Mapped[int | None] = mapped_column(BigInteger)
    counts: Mapped[dict] = mapped_column(JSON)
    timings: Mapped[dict] = mapped_column(JSON)


class MetricTotals(Base):
    __tablename__ = "telemetry_metric_totals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    counts: Mapped[dict] = mapped_column(JSON)


class MetricSample(Base):
    __tablename__ = "telemetry_metric_samples"
    __table_args__ = (Index("ix_telemetry_samples_sampled", "sampled_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lag: Mapped[int | None] = mapped_column(BigInteger)
    counts: Mapped[dict] = mapped_column(JSON)
    timings: Mapped[dict] = mapped_column(JSON)


class ReportedDeadLetter(Base):
    __tablename__ = "telemetry_reported_dead_letters"
    __table_args__ = (Index("ix_telemetry_reported_dlq_rejected", "rejected_at"),)

    topic: Mapped[str] = mapped_column(String(200), primary_key=True)
    partition: Mapped[int] = mapped_column(Integer, primary_key=True)
    offset: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    rejected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    category: Mapped[str] = mapped_column(String(40))
    event_id: Mapped[UUID | None] = mapped_column(Uuid)
