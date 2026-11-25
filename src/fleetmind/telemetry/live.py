"""Read committed assessments and stream bounded, replayable pages."""

import asyncio
from contextlib import aclosing
from dataclasses import dataclass
from threading import BoundedSemaphore
from time import monotonic

import anyio
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from fleetmind.api.schemas import AlertLevel, PredictionHistoryResponse
from fleetmind.db.database import SessionLocal
from fleetmind.db.models import PredictionHistory
from fleetmind.security.protect import stream_allowed
from fleetmind.telemetry.live_models import StreamCursor, StreamRecord
from fleetmind.telemetry.live_schemas import AssessmentEvent, CursorEvent, StreamProblem
from fleetmind.telemetry.storage import TelemetryAssessment

POLL_SECONDS = 0.5
HEARTBEAT_SECONDS = 10
MAX_CONNECTION_SECONDS = 300
BATCH_SIZE = 64
SNAPSHOT_LOOKBACK = 4096
CONNECTIONS = BoundedSemaphore(32)
SEND_TIMEOUT = 10


@dataclass(frozen=True)
class FeedFilter:
    asset_id: str | None = None
    alert_level: AlertLevel | None = None


def storage_state(error):
    code = getattr(getattr(error, "orig", None), "sqlstate", None)
    return "migration_required" if code == "42P01" else "unavailable"


def high_watermark(db):
    return db.execute(
        select(StreamCursor.position).where(StreamCursor.id == 1)
    ).scalar_one()


def assessment_rows(db, filters: FeedFilter, high, *, after=None, limit=BATCH_SIZE):
    query = (
        select(StreamRecord.position, TelemetryAssessment, PredictionHistory)
        .join(
            TelemetryAssessment, TelemetryAssessment.event_id == StreamRecord.event_id
        )
        .join(
            PredictionHistory, PredictionHistory.id == TelemetryAssessment.prediction_id
        )
        .where(StreamRecord.position <= high)
    )
    if filters.asset_id is not None:
        query = query.where(PredictionHistory.asset_id == filters.asset_id)
    if filters.alert_level is not None:
        query = query.where(PredictionHistory.alert_level == filters.alert_level)
    if after is None:
        query = query.where(StreamRecord.position > max(0, high - SNAPSHOT_LOOKBACK))
        query = query.order_by(StreamRecord.position.desc())
    else:
        query = query.where(StreamRecord.position > after).order_by(
            StreamRecord.position
        )
    return [
        AssessmentEvent(
            cursor=str(position),
            event_id=receipt.event_id,
            observed_at=receipt.observed_at,
            ingested_at=receipt.ingested_at,
            assessed_at=receipt.assessed_at,
            prediction=PredictionHistoryResponse.model_validate(prediction),
        )
        for position, receipt, prediction in db.execute(query.limit(limit))
    ]


class FeedReader:
    def __init__(self, factory=SessionLocal):
        self.factory = factory

    def read(self, filters, after, limit=BATCH_SIZE):
        with self.factory() as db:
            high = high_watermark(db)
            scanned = high if after is None else min(high, after + limit)
            events = (
                assessment_rows(db, filters, scanned, after=after, limit=limit)
                if after is None or scanned > after
                else []
            )
            return high, scanned, events

    def tail(self):
        with self.factory() as db:
            return high_watermark(db)


def encode(kind, payload, cursor=None):
    identifier = f"id: {cursor}\n" if cursor is not None else ""
    return f"{identifier}event: {kind}\ndata: {payload.model_dump_json()}\n\n".encode()


async def committed_stream(request, reader, filters, after, *, slots=CONNECTIONS):
    if not slots.acquire(blocking=False):
        yield encode(
            "unavailable", StreamProblem(detail="Live connection limit reached.")
        )
        return
    try:
        if not await stream_allowed(request, force=True):
            yield encode(
                "session_expired",
                StreamProblem(detail="Sign in again to resume telemetry."),
            )
            return
        high = await run_in_threadpool(reader.tail)
        if after is not None and after > high:
            yield encode("reset", CursorEvent(cursor=str(high)), high)
            return
        cursor = high if after is None else after
        yield encode("ready", CursorEvent(cursor=str(cursor)), cursor)
        expiry = monotonic() + MAX_CONNECTION_SECONDS
        next_heartbeat = monotonic() + HEARTBEAT_SECONDS
        while monotonic() < expiry and not await request.is_disconnected():
            if not await stream_allowed(request):
                yield encode(
                    "session_expired",
                    StreamProblem(detail="Sign in again to resume telemetry."),
                )
                return
            high, scanned, events = await run_in_threadpool(
                reader.read, filters, cursor
            )
            if high < cursor:
                yield encode("reset", CursorEvent(cursor=str(high)), high)
                return
            for event in events:
                cursor = int(event.cursor)
                yield encode("assessment", event, cursor)
            if scanned > cursor:
                cursor = scanned
                yield encode("cursor", CursorEvent(cursor=str(cursor)), cursor)
            if monotonic() >= next_heartbeat:
                yield encode("heartbeat", CursorEvent(cursor=str(cursor)), cursor)
                next_heartbeat = monotonic() + HEARTBEAT_SECONDS
            if cursor >= high:
                await asyncio.sleep(POLL_SECONDS)
    except SQLAlchemyError as exc:
        detail = (
            "Apply the live telemetry migration."
            if storage_state(exc) == "migration_required"
            else "Telemetry storage is unavailable."
        )
        yield encode("unavailable", StreamProblem(detail=detail))
    finally:
        slots.release()


class LiveStreamResponse(StreamingResponse):
    """Bound ASGI writes and always close the iterator on disconnect or timeout."""

    async def stream_response(self, send):
        try:
            async with aclosing(self.body_iterator) as body:
                with anyio.fail_after(SEND_TIMEOUT):
                    await send(
                        {
                            "type": "http.response.start",
                            "status": self.status_code,
                            "headers": self.raw_headers,
                        }
                    )
                async for chunk in body:
                    with anyio.fail_after(SEND_TIMEOUT):
                        await send(
                            {
                                "type": "http.response.body",
                                "body": chunk,
                                "more_body": True,
                            }
                        )
            with anyio.move_on_after(SEND_TIMEOUT):
                await send(
                    {"type": "http.response.body", "body": b"", "more_body": False}
                )
        except TimeoutError:
            # A blocked connection is abandoned so the client can reconnect.
            return
