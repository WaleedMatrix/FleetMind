"""Read-only live monitoring response contracts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from fleetmind.api.schemas import PredictionHistoryResponse
from fleetmind.telemetry.contracts import DeadLetter

StorageState = Literal["ready", "migration_required", "unavailable"]
Availability = Literal["available", "unavailable", "stale", "unknown", "stopped"]


class AssessmentEvent(BaseModel):
    cursor: str
    event_id: UUID
    observed_at: datetime
    ingested_at: datetime
    assessed_at: datetime
    prediction: PredictionHistoryResponse


class AssessmentSnapshot(BaseModel):
    state: StorageState
    cursor: str | None = None
    items: list[AssessmentEvent] = Field(default_factory=list)


class CursorEvent(BaseModel):
    cursor: str


class StreamProblem(BaseModel):
    detail: str


class Counters(BaseModel):
    received: int = 0
    processed: int = 0
    duplicates: int = 0
    invalid: int = 0
    retried_events: int = 0
    retry_attempts: int = 0
    dead_lettered: int = 0
    committed: int = 0


class MetricPoint(BaseModel):
    started_at: datetime
    received_per_s: float | None = None
    committed_per_s: float | None = None
    max_worker_lag: int | None = None
    inference_ms: float | None = None
    database_ms: float | None = None
    observation_to_commit_ms: float | None = None


class MonitoringMetrics(BaseModel):
    state: StorageState
    as_of: datetime
    window_seconds: int = 300
    bucket_seconds: int = 10
    stale_after_seconds: int = 20
    worker: Availability = "unknown"
    broker: Availability = "unknown"
    active_workers: int | None = None
    last_report_at: datetime | None = None
    last_broker_probe_at: datetime | None = None
    last_assessed_at: datetime | None = None
    durable_assessments: int | None = None
    reported_totals: Counters | None = None
    max_worker_lag: int | None = None
    truncated: bool = False
    points: list[MetricPoint] = Field(default_factory=list)


class DeadLetterSnapshot(BaseModel):
    state: StorageState
    last_report_at: datetime | None = None
    items: list[DeadLetter] = Field(default_factory=list)
