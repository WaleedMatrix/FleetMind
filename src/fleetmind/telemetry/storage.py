"""Atomic telemetry assessment storage and durable event-ID deduplication."""

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from time import perf_counter
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Mapped, mapped_column

from fleetmind.db.database import Base
from fleetmind.services.predictions import assess, validate_asset
from fleetmind.telemetry.contracts import RejectedCategory, TelemetryEvent


class TelemetryAssessment(Base):
    __tablename__ = "telemetry_assessments"
    __table_args__ = (
        CheckConstraint("schema_version = 1", name="ck_telemetry_schema_version"),
        Index("ix_telemetry_ingested_at", "ingested_at"),
        Index("ix_telemetry_assessed_at", "assessed_at"),
    )

    event_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    prediction_id: Mapped[int] = mapped_column(
        ForeignKey(
            "prediction_history.id", name="fk_telemetry_prediction", ondelete="RESTRICT"
        ),
        unique=True,
    )
    schema_version: Mapped[int]
    event_hash: Mapped[str] = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EventRejected(ValueError):
    def __init__(self, category: RejectedCategory):
        self.category = category


class ConcurrentDelivery(Exception):
    """Roll back the losing prediction before looking up the winning receipt."""


@dataclass(frozen=True)
class Outcome:
    prediction_id: int
    duplicate: bool
    inference_ms: float | None = None
    database_ms: float | None = None


class TelemetryStore:
    def __init__(self, factory, model):
        self.factory = factory
        self.model = model

    @staticmethod
    def _duplicate(row: TelemetryAssessment, digest: str) -> Outcome:
        if row.event_hash != digest:
            raise EventRejected("event_id_conflict")
        return Outcome(row.prediction_id, duplicate=True)

    def persist(self, event: TelemetryEvent, ingested_at: datetime) -> Outcome:
        digest = sha256(event.model_dump_json().encode()).hexdigest()
        started = perf_counter()
        try:
            with self.factory.begin() as db:
                existing = db.get(TelemetryAssessment, event.event_id)
                if existing is not None:
                    return self._duplicate(existing, digest)
                validate_asset(db, event.asset_id, event)
                inference_start = perf_counter()
                prediction = assess(
                    db,
                    self.model,
                    event,
                    asset_id=event.asset_id,
                    source=event.source,
                )
                inference_ms = (perf_counter() - inference_start) * 1000
                db.flush()
                row = (
                    insert(TelemetryAssessment)
                    .values(
                        event_id=event.event_id,
                        prediction_id=prediction.id,
                        schema_version=event.schema_version,
                        event_hash=digest,
                        observed_at=event.observed_at,
                        ingested_at=ingested_at,
                        assessed_at=prediction.created_at,
                    )
                    .on_conflict_do_nothing(
                        index_elements=[TelemetryAssessment.event_id]
                    )
                )
                if (
                    db.execute(
                        row.returning(TelemetryAssessment.event_id)
                    ).scalar_one_or_none()
                    is None
                ):
                    raise ConcurrentDelivery
                prediction_id = prediction.id
        except ConcurrentDelivery:
            with self.factory() as db:
                return self._duplicate(
                    db.get_one(TelemetryAssessment, event.event_id), digest
                )
        return Outcome(
            prediction_id,
            duplicate=False,
            inference_ms=inference_ms,
            database_ms=(perf_counter() - started) * 1000 - inference_ms,
        )
