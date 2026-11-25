"""Live telemetry ordering, replay, backpressure, and persistent diagnostics."""

import asyncio
import os
import random
from datetime import UTC, datetime, timedelta
from threading import BoundedSemaphore
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from fleetmind.db.models import Asset, PredictionHistory
from fleetmind.services.predictions import load_frozen_model
from fleetmind.telemetry import live
from fleetmind.telemetry.contracts import DeadLetter
from fleetmind.telemetry.live_schemas import CursorEvent
from fleetmind.telemetry.monitoring import dead_letters, metrics
from fleetmind.telemetry.reporting import DiagnosticSnapshot, save_snapshot
from fleetmind.telemetry.storage import TelemetryAssessment, TelemetryStore
from scripts.produce_telemetry import simulate_event
from scripts.telemetry_worker import worker_engine

TEST_URL = os.getenv("FLEETMIND_MIGRATION_TEST_DATABASE_URL")


class Request:
    disconnected = False

    async def is_disconnected(self):
        return self.disconnected


class Reader:
    def tail(self):
        return 12

    def read(self, filters, cursor):
        return 12, min(cursor + 2, 12), []


def test_stream_resume_advances_filtered_cursor_and_releases_slot_on_disconnect():
    async def exercise():
        slots = BoundedSemaphore(1)
        request = Request()
        stream = live.committed_stream(
            request, Reader(), live.FeedFilter(), 5, slots=slots
        )
        assert await anext(stream) == live.encode("ready", CursorEvent(cursor="5"), 5)
        assert await anext(stream) == live.encode("cursor", CursorEvent(cursor="7"), 7)
        assert not slots.acquire(blocking=False)
        request.disconnected = True
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
        assert slots.acquire(blocking=False)
        slots.release()
        resumed = live.committed_stream(
            Request(), Reader(), live.FeedFilter(), 7, slots=slots
        )
        assert b"id: 7\n" in await anext(resumed)
        assert b"id: 9\n" in await anext(resumed)
        await resumed.aclose()
        invalid = live.committed_stream(
            Request(), Reader(), live.FeedFilter(), 99, slots=slots
        )
        assert b"event: reset" in await anext(invalid)
        await invalid.aclose()

    asyncio.run(exercise())


def test_heartbeat_and_slow_client_cleanup(monkeypatch):
    monkeypatch.setattr(live, "SEND_TIMEOUT", 0.02)
    monkeypatch.setattr(live, "HEARTBEAT_SECONDS", 0)
    slots = BoundedSemaphore(1)

    async def exercise():
        stream = live.committed_stream(
            Request(), Reader(), live.FeedFilter(), None, slots=slots
        )
        assert b"event: ready" in await anext(stream)
        assert b"event: heartbeat" in await anext(stream)
        await stream.aclose()

        async def slow_send(message):
            if message["type"] == "http.response.body":
                await asyncio.sleep(10)

        response = live.LiveStreamResponse(
            live.committed_stream(
                Request(), Reader(), live.FeedFilter(), None, slots=slots
            ),
        )
        await asyncio.wait_for(response.stream_response(slow_send), timeout=1)
        assert slots.acquire(blocking=False)
        slots.release()

    asyncio.run(exercise())


@pytest.fixture
def store():
    if not TEST_URL:
        pytest.skip("Requires migrated disposable PostgreSQL")
    engine = worker_engine(TEST_URL, pool_size=3)
    factory = sessionmaker(bind=engine)
    asset = f"live-test-{uuid4().hex[:10]}"
    try:
        with factory.begin() as db:
            assert db.scalar(text("SELECT current_database()")).endswith("_test")
            db.add(Asset(asset_id=asset, display_name="Live fixture", machine_type="M"))
        yield factory, asset
    finally:
        engine.dispose()


def test_commit_order_beats_prediction_id_and_filters_are_resumable(store):
    factory, asset = store
    reader = live.FeedReader(factory)
    start = reader.tail()
    now = datetime.now(UTC)
    frames = random.Random(3)
    first = simulate_event(frames, "normal", asset, "M")
    second = simulate_event(frames, "stress", asset, "M")
    with factory() as db, db.begin():
        prediction = PredictionHistory(
            **first.model_dump(
                include={
                    "machine_type",
                    "source",
                    "asset_id",
                    "air_temperature_k",
                    "process_temperature_k",
                    "rotational_speed_rpm",
                    "torque_nm",
                    "tool_wear_min",
                }
            ),
            failure_score=0.4,
            predicted_failure=False,
            alert_level="review",
            model_version="test-fixture",
        )
        db.add(prediction)
        db.flush()
        delayed_prediction_id = prediction.id
        worker = TelemetryStore(factory, load_frozen_model())
        fast = worker.persist(second, now)
        high, _, delivered = reader.read(live.FeedFilter(asset), start)
        assert [row.event_id for row in delivered] == [second.event_id]
        assert fast.prediction_id > delayed_prediction_id
        db.add(
            TelemetryAssessment(
                event_id=first.event_id,
                prediction_id=prediction.id,
                schema_version=1,
                event_hash="fixture",
                observed_at=now,
                ingested_at=now,
                assessed_at=now,
            )
        )
        db.flush()
        assert reader.tail() == high
    _, _, resumed = reader.read(live.FeedFilter(asset, "review"), high)
    assert [row.event_id for row in resumed] == [first.event_id]
    assert resumed[0].prediction.prediction_id == delayed_prediction_id
    assert not reader.read(live.FeedFilter(asset, "high_priority"), high)[2]
    assert not reader.read(live.FeedFilter("never-registered"), start)[2]
    assert not reader.read(live.FeedFilter(asset), int(resumed[0].cursor))[2]


def test_persisted_worker_totals_are_idempotent_and_staleness_is_explicit(store):
    factory, _ = store
    now = datetime.now(UTC)
    from fleetmind.telemetry.live_schemas import Counters

    with factory() as db:
        initial = metrics(db, now).reported_totals or Counters()
    old = uuid4()
    letter = DeadLetter(
        category="invalid_payload",
        rejected_at=now,
        original_topic=f"test-{uuid4().hex[:12]}",
        original_offset=1,
        original_partition=0,
    )
    first = DiagnosticSnapshot(
        sampled_at=now,
        running=True,
        lag=3,
        counts=Counters(received=3, committed=3).model_dump(),
        timings={"inference_ms": (2, 10)},
        letters=(letter,),
    )
    save_snapshot(factory, old, first, True)
    save_snapshot(factory, old, first, True)
    restart = DiagnosticSnapshot(
        sampled_at=now + timedelta(seconds=5),
        running=True,
        lag=None,
        counts=Counters(received=2, committed=1).model_dump(),
        timings={},
        letters=(letter,),
    )
    save_snapshot(factory, uuid4(), restart, False)
    with factory() as db:
        data = metrics(db, now + timedelta(seconds=6))
        assert (data.worker, data.broker) == ("available", "available")
        assert data.reported_totals.received == initial.received + 5
        assert data.reported_totals.committed == initial.committed + 4
        assert data.max_worker_lag == 3
        assert any(point.inference_ms == 5 for point in data.points)
        assert (
            sum(
                row.original_topic == letter.original_topic
                for row in dead_letters(db, 50).items
            )
            == 1
        )
        stale = metrics(db, now + timedelta(seconds=45))
        assert (stale.worker, stale.broker, stale.max_worker_lag) == (
            "stale",
            "stale",
            None,
        )
        assert stale.reported_totals.received == initial.received + 5
