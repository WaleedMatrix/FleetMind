"""Read durable telemetry status without contacting the broker."""

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from fleetmind.api.dependencies import DBSession
from fleetmind.api.schemas import AlertLevel, AssetId
from fleetmind.telemetry.contracts import TelemetryStatus
from fleetmind.telemetry.live import (
    FeedFilter,
    FeedReader,
    LiveStreamResponse,
    committed_stream,
    storage_state,
)
from fleetmind.telemetry.live_schemas import (
    AssessmentSnapshot,
    DeadLetterSnapshot,
    MonitoringMetrics,
)
from fleetmind.telemetry.monitoring import dead_letters, metrics
from fleetmind.telemetry.storage import TelemetryAssessment

router = APIRouter(prefix="/api/v1/telemetry", tags=["telemetry"])
Cursor = Annotated[str | None, Query(pattern=r"^[0-9]{1,19}$")]
Limit = Annotated[int, Query(ge=1, le=50)]


@router.get("/status", response_model=TelemetryStatus)
def status(db: DBSession):
    try:
        count, ingested, assessed = db.execute(
            select(
                func.count(TelemetryAssessment.event_id),
                func.max(TelemetryAssessment.ingested_at),
                func.max(TelemetryAssessment.assessed_at),
            )
        ).one()
    except SQLAlchemyError as exc:
        if getattr(getattr(exc, "orig", None), "sqlstate", None) == "42P01":
            return TelemetryStatus(state="migration_required")
        return TelemetryStatus(state="unavailable")
    return TelemetryStatus(
        state="ready",
        persisted_assessments=count,
        last_ingested_at=ingested,
        last_assessed_at=assessed,
    )


@router.get("/assessments", response_model=AssessmentSnapshot)
def assessments(
    asset_id: AssetId | None = None,
    alert_level: AlertLevel | None = None,
    limit: Limit = 30,
):
    try:
        high, _, rows = FeedReader().read(
            FeedFilter(asset_id, alert_level), None, limit
        )
    except SQLAlchemyError as exc:
        return AssessmentSnapshot(state=storage_state(exc))
    return AssessmentSnapshot(state="ready", cursor=str(high), items=rows)


@router.get("/stream", response_class=LiveStreamResponse)
async def live_stream(
    request: Request,
    cursor: Cursor = None,
    asset_id: AssetId | None = None,
    alert_level: AlertLevel | None = None,
    last_event_id: Annotated[str | None, Header()] = None,
):
    raw = last_event_id if last_event_id else cursor
    if raw is not None and (
        len(raw) > 19
        or not raw.isascii()
        or not raw.isdecimal()
        or int(raw) > 9_223_372_036_854_775_807
    ):
        raise HTTPException(status_code=422, detail="Invalid telemetry cursor.")
    return LiveStreamResponse(
        committed_stream(
            request,
            FeedReader(),
            FeedFilter(asset_id, alert_level),
            int(raw) if raw is not None else None,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.get("/metrics", response_model=MonitoringMetrics)
def telemetry_metrics(db: DBSession):
    return metrics(db)


@router.get("/dead-letters", response_model=DeadLetterSnapshot)
def telemetry_dead_letters(db: DBSession, limit: Limit = 20):
    return dead_letters(db, limit)
