"""Real PostgreSQL and Kafka interoperability and restart recovery."""

import os
import random
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from threading import Barrier, Event, Timer
from time import monotonic
from uuid import uuid4

import pytest
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import func, select, text
from sqlalchemy.orm import sessionmaker

from fleetmind.db.models import Asset, PredictionHistory
from fleetmind.services.predictions import load_frozen_model
from fleetmind.telemetry.broker import (
    BrokerSettings,
    Publisher,
    create_consumer,
    ensure_topics,
    kafka,
)
from fleetmind.telemetry.contracts import DeadLetter
from fleetmind.telemetry.live import FeedFilter, FeedReader
from fleetmind.telemetry.storage import TelemetryAssessment, TelemetryStore
from fleetmind.telemetry.worker import TelemetryWorker, WorkerHalt
from scripts.produce_telemetry import simulate_event
from scripts.telemetry_worker import worker_engine

TEST_URL = os.getenv("FLEETMIND_TELEMETRY_TEST_DATABASE_URL")
TEST_BROKER = os.getenv("FLEETMIND_TELEMETRY_TEST_BOOTSTRAP")
pytestmark = pytest.mark.skipif(
    not TEST_URL or not TEST_BROKER,
    reason="Requires disposable PostgreSQL and Kafka",
)


@pytest.fixture
def environment():
    pytest.importorskip("confluent_kafka")
    prefix = f"fleetmind-it-{uuid4().hex[:12]}"
    engine = worker_engine(TEST_URL, pool_size=2)
    factory = sessionmaker(engine)
    with factory.begin() as db:
        name = db.scalar(text("SELECT current_database()"))
        assert name.startswith("fleetmind_") and name.endswith("_test")
        db.add(
            Asset(asset_id=prefix, display_name="Integration fixture", machine_type="M")
        )
    settings = BrokerSettings(TEST_BROKER, f"{prefix}.in", f"{prefix}.dlq", prefix)
    ensure_topics(settings)
    try:
        yield prefix, factory, settings
    finally:
        engine.dispose()


def quiet(*_, **__):
    pass


def run_bounded(worker, count):
    deadline = Timer(25, worker.stop.set)
    deadline.start()
    try:
        worker.run(max_events=count)
    finally:
        deadline.cancel()


def test_restart_replays_committed_database_effect_and_rejects_bad_events(environment):
    asset_id, factory, settings = environment
    store = TelemetryStore(factory, load_frozen_model())
    publish = Publisher(settings)
    rng = random.Random(3)
    event = simulate_event(rng, "normal", asset_id, "M")
    payload = event.model_dump_json().encode()
    first = publish.publish(settings.topic, asset_id, payload)

    class FailingCommit:
        def __init__(self):
            self.client = create_consumer(settings, quiet)

        def __getattr__(self, name):
            return getattr(self.client, name)

        def commit(self, **_):
            raise WorkerHalt(
                "Simulated exit immediately before Kafka offset acknowledgement."
            )

    before_restart = TelemetryWorker(
        FailingCommit(),
        publish,
        store,
        settings,
        Event(),
        emit=quiet,
    )
    with pytest.raises(WorkerHalt, match="Simulated exit"):
        run_bounded(before_restart, 1)
    with factory() as db:
        original = db.get_one(TelemetryAssessment, event.event_id).prediction_id
        assert db.get_one(PredictionHistory, original).source == "simulated"

    publish.publish(settings.topic, asset_id, payload)
    publish.publish(settings.topic, asset_id, b"malformed confidential input")
    mismatch = simulate_event(rng, "stress", asset_id, "H")
    publish.publish(settings.topic, asset_id, mismatch.model_dump_json().encode())
    changed = event.model_copy(update={"torque_nm": event.torque_nm + 1})
    publish.publish(settings.topic, asset_id, changed.model_dump_json().encode())
    missing = simulate_event(rng, "normal", asset_id + "-missing", "M")
    publish.publish(
        settings.topic, missing.asset_id, missing.model_dump_json().encode()
    )
    valid = simulate_event(rng, "stress", asset_id, "M")
    publish.publish(settings.topic, asset_id, valid.model_dump_json().encode())
    emitted = []
    consumer = create_consumer(settings, quiet)
    worker = TelemetryWorker(
        consumer,
        publish,
        store,
        settings,
        Event(),
        emit=lambda name, **fields: emitted.append((name, fields)),
        trace=True,
    )
    run_bounded(worker, 7)
    assert worker.counts["duplicates"] == 2
    assert worker.counts["processed"] == 1
    assert worker.counts["dead_lettered"] == 4
    offsets = [
        fields["offset"]
        for name, fields in emitted
        if name == "event_handled" and fields["partition"] == first.partition()
    ]
    assert offsets == sorted(offsets) and offsets[0] == first.offset()

    with factory() as db:
        assert db.get_one(TelemetryAssessment, event.event_id).prediction_id == original
        assert (
            db.scalar(
                select(func.count())
                .select_from(PredictionHistory)
                .where(
                    PredictionHistory.asset_id == asset_id,
                )
            )
            == 2
        )
        receipt = db.get_one(TelemetryAssessment, valid.event_id)
        assert receipt.observed_at == valid.observed_at
        assert receipt.ingested_at <= receipt.assessed_at

    client = kafka()
    dlq = client.Consumer(
        {"bootstrap.servers": settings.bootstrap, "group.id": settings.group + ".audit"}
    )
    letters = []
    try:
        dlq.assign([client.TopicPartition(settings.dead_letter_topic, 0, 0)])
        deadline = monotonic() + 12
        while len(letters) < 4 and monotonic() < deadline:
            message = dlq.poll(1)
            if message is not None and message.error() is None:
                assert b"confidential" not in message.value()
                letters.append(DeadLetter.model_validate_json(message.value()))
    finally:
        dlq.close()
    assert {letter.category for letter in letters} == {
        "invalid_payload",
        "missing_asset",
        "machine_type_mismatch",
        "event_id_conflict",
    }


def test_concurrent_database_delivery_has_one_assessment(environment):
    asset_id, factory, _ = environment
    event = simulate_event(random.Random(5), "normal", asset_id, "M")
    # Read the same model separately to keep this storage race test independent
    # of inference-library thread scheduling.
    gate = Barrier(2)

    class RacingModel:
        def __init__(self):
            self.model = load_frozen_model()

        def predict_proba(self, frame):
            gate.wait(timeout=10)
            return self.model.predict_proba(frame)

    stores = [TelemetryStore(factory, RacingModel()) for _ in range(2)]
    with ThreadPoolExecutor(2) as pool:
        futures = [
            pool.submit(store.persist, event, datetime.now(UTC)) for store in stores
        ]
        results = [future.result(timeout=15) for future in futures]
    assert sorted(row.duplicate for row in results) == [False, True]
    assert len({row.prediction_id for row in results}) == 1
    with factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(PredictionHistory)
                .where(
                    PredictionHistory.asset_id == asset_id,
                )
            )
            == 1
        )


def test_two_consumer_process_paths_share_durable_deduplication_and_cursor(environment):
    asset_id, factory, settings = environment
    replay = replace(settings, group=settings.group + ".replay")
    event = simulate_event(random.Random(17), "normal", asset_id, "M")
    reader = FeedReader(factory)
    high = reader.tail()
    publish = Publisher(settings)
    publish.publish(settings.topic, asset_id, event.model_dump_json().encode())
    gate = Barrier(2)

    class RacingModel:
        def __init__(self):
            self.model = load_frozen_model()

        def predict_proba(self, frame):
            gate.wait(timeout=15)
            return self.model.predict_proba(frame)

    workers = [
        TelemetryWorker(
            None,
            publish,
            TelemetryStore(factory, RacingModel()),
            config,
            Event(),
            emit=quiet,
        )
        for config in (settings, replay)
    ]

    # Distinct groups deliberately deliver the same event to both workers.
    # A normal shared group partitions ownership and can redeliver on recovery.
    def consume(worker):
        worker.consumer = create_consumer(worker.settings, quiet)
        run_bounded(worker, 1)

    with ThreadPoolExecutor(2) as pool:
        pending = [pool.submit(consume, worker) for worker in workers]
        for future in pending:
            future.result(timeout=28)
    assert [worker.counts["committed"] for worker in workers] == [1, 1]
    assert sum(worker.counts["processed"] for worker in workers) == 1
    assert sum(worker.counts["duplicates"] for worker in workers) == 1
    _, _, committed = reader.read(FeedFilter(asset_id), high)
    assert [item.event_id for item in committed] == [event.event_id]


def test_database_disconnect_retries_without_skipping_the_offset(environment):
    asset_id, factory, settings = environment
    event = simulate_event(random.Random(11), "stress", asset_id, "M")
    publisher = Publisher(settings)
    publisher.publish(settings.topic, asset_id, event.model_dump_json().encode())
    bound = factory.kw["bind"]
    admin = worker_engine(TEST_URL)
    interrupted = Event()

    def drop_connection(connection, _cursor, statement, *_):
        if "FROM telemetry_assessments" not in statement or interrupted.is_set():
            return
        interrupted.set()
        victim = connection.connection.driver_connection.info.backend_pid
        with admin.connect() as other:
            assert other.scalar(
                text("SELECT pg_terminate_backend(:pid)"), {"pid": victim}
            )

    sqlalchemy_event.listen(bound, "before_cursor_execute", drop_connection)
    try:
        worker = TelemetryWorker(
            create_consumer(settings, quiet),
            publisher,
            TelemetryStore(factory, load_frozen_model()),
            settings,
            Event(),
            emit=quiet,
        )
        run_bounded(worker, 1)
    finally:
        sqlalchemy_event.remove(bound, "before_cursor_execute", drop_connection)
        admin.dispose()
    assert interrupted.is_set()
    assert worker.counts["retry_attempts"] == 1
    assert worker.counts["committed"] == 1
    assert worker.counts["dead_lettered"] == 0
    with factory() as db:
        assert db.get_one(TelemetryAssessment, event.event_id)


def test_graceful_shutdown_leaves_idle_consumer_group(environment):
    _, factory, settings = environment
    assigned = Event()
    stop = Event()
    diagnostics = []

    def on_rebalance(kind, **_):
        if kind == "assigned":
            assigned.set()

    worker = TelemetryWorker(
        create_consumer(settings, on_rebalance),
        Publisher(settings),
        TelemetryStore(factory, load_frozen_model()),
        settings,
        stop,
        emit=lambda name, **fields: diagnostics.append((name, fields)),
    )
    with ThreadPoolExecutor(1) as pool:
        task = pool.submit(worker.run)
        try:
            assert assigned.wait(15)
        finally:
            stop.set()
        task.result(timeout=10)
    assert diagnostics[-1][0] == "worker_stopped"
    assert diagnostics[-1][1]["committed"] == 0
