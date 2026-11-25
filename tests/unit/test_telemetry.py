"""Telemetry contracts and failure ordering without a broker."""

import json
import random
from datetime import UTC, datetime
from threading import Event
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from fleetmind.telemetry.broker import BrokerFailure, BrokerSettings, ConsumerLag
from fleetmind.telemetry.contracts import TelemetryEvent
from fleetmind.telemetry.storage import Outcome
from fleetmind.telemetry.worker import TelemetryWorker, WorkerHalt, decode
from scripts.produce_telemetry import simulate_event


class Message:
    def __init__(self, body, key=b"unit-test"):
        self.body = body
        self.asset_key = key

    def value(self):
        return self.body

    def key(self):
        return self.asset_key

    def topic(self):
        return "fleetmind.unit"

    def partition(self):
        return 2

    def offset(self):
        return 7


def payload():
    return simulate_event(random.Random(8), "stress", "unit-test", "H").model_dump(
        mode="json"
    )


def test_telemetry_uses_strict_versioned_utc_contract_and_seeded_values():
    base = payload()
    assert base["source"] == "simulated"
    repeat = payload()
    assert repeat["event_id"] != base["event_id"]
    for field in ("observed_at", "event_id"):
        repeat.pop(field)
    assert repeat == {key: value for key, value in base.items() if key in repeat}
    assert decode(Message(json.dumps(base).encode())).machine_type == "H"
    for change in (
        {"observed_at": "2026-01-04T01:00:00+01:00"},
        {"observed_at": "2026-01-04T00:00:00"},
        {"schema_version": True},
        {"schema_version": 2},
        {"schema_version": "1"},
        {"source": "manual"},
        {"torque_nm": "22.0"},
        {"air_temperature_k": 0},
        {"process_temperature_k": 1e20},
        {"extra": "unknown"},
    ):
        with pytest.raises(ValidationError):
            TelemetryEvent.model_validate_json(json.dumps(base | change))


def fixture(persist, publish, *, retries=0, stop=None, commit_ok=True):
    calls = []

    def commit(*, message, asynchronous):
        assert not asynchronous
        calls.append(message.offset())
        return [SimpleNamespace(error=None if commit_ok else "failed")]

    return TelemetryWorker(
        SimpleNamespace(commit=commit),
        SimpleNamespace(publish=publish),
        SimpleNamespace(persist=persist),
        BrokerSettings("127.0.0.1:19092"),
        stop or Event(),
        retries=retries,
        emit=lambda *_, **__: None,
        trace=True,
    ), calls


def test_offsets_follow_durable_processing_and_duplicate_metadata_is_skipped():
    offsets = []

    def persist(*_):
        assert not offsets
        return Outcome(1, duplicate=True)

    worker, offsets = fixture(persist, lambda *_: pytest.fail("Unexpected DLQ"))
    worker.process(Message(json.dumps(payload()).encode()))
    assert offsets == [7]
    assert worker.counts["duplicates"] == 1
    assert not worker.samples["inference_ms"]


def test_rejected_delivery_requires_dlq_ack_and_redacts_contents():
    raw = b'{"credential":"ORIGINAL_SECRET"}'

    def publish(topic, key, body):
        assert topic == "fleetmind.telemetry.dlq.v1"
        assert key == "fleetmind.unit:2:7"
        assert b"ORIGINAL_SECRET" not in body
        assert json.loads(body)["category"] == "invalid_payload"
        raise BrokerFailure

    worker, offsets = fixture(lambda *_: pytest.fail("Must not persist"), publish)
    with pytest.raises(BrokerFailure):
        worker.process(Message(raw))
    assert offsets == []
    assert worker.counts["invalid"] == 1
    assert worker.counts["dead_lettered"] == 0


def test_exhausted_database_retries_and_commit_failure_leave_offset_unacknowledged():
    attempts = []

    def unavailable(*_):
        attempts.append(True)
        raise OperationalError("ignored", {}, RuntimeError())

    worker, offsets = fixture(
        unavailable, lambda *_: pytest.fail("Unexpected DLQ"), retries=1
    )
    message = Message(json.dumps(payload()).encode())
    with pytest.raises(WorkerHalt, match="retries exhausted"):
        worker.process(message)
    assert len(attempts) == 2
    assert worker.counts["retried_events"] == worker.counts["retry_attempts"] == 1
    assert offsets == []
    worker, offsets = fixture(
        lambda *_: Outcome(1, False, 1.0, 1.0),
        lambda *_: None,
        commit_ok=False,
    )
    with pytest.raises(WorkerHalt, match="acknowledgement"):
        worker.process(message)
    assert worker.counts["processed"] == 1
    assert worker.counts["committed"] == 0
    assert offsets == [7]


def test_shutdown_interrupts_retry_and_keeps_event_pending():
    stop = Event()

    def stop_on_failure(*_):
        stop.set()
        raise OperationalError("ignored", {}, RuntimeError())

    worker, offsets = fixture(
        stop_on_failure, lambda *_: pytest.fail("Unexpected DLQ"), retries=2, stop=stop
    )
    with pytest.raises(WorkerHalt, match="Shutdown"):
        worker.process(Message(json.dumps(payload()).encode()))
    assert offsets == []
    assert worker.counts["retry_attempts"] == 0


def test_correct_asset_key_and_observation_timezone():
    value = payload()
    value["observed_at"] = datetime.now(UTC).isoformat()
    with pytest.raises(ValueError) as failure:
        decode(Message(json.dumps(value).encode(), b"wrong-key"))
    assert failure.value.category == "partition_key_mismatch"


def test_consumer_lag_requires_available_samples_for_the_assignment():
    lag = ConsumerLag("fleetmind.unit")
    assert lag.read() is None
    parts = {
        "0": {"fetch_state": "active", "consumer_lag": 4},
        "1": {"fetch_state": "active", "hi_offset": 0},
    }
    stats = {
        "cgrp": {"assignment_size": 2},
        "topics": {"fleetmind.unit": {"partitions": parts}},
    }
    lag.update(json.dumps(stats))
    assert lag.read() == 4
    parts["1"]["hi_offset"] = 20
    lag.update(json.dumps(stats))
    assert lag.read() is None
    lag.update("bad sample")
    assert lag.read() is None
