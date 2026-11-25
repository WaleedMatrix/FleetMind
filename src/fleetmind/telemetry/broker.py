"""Small synchronous Kafka boundary for acknowledged delivery and offsets."""

import importlib
import json
import os
import re
import signal
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Event
from time import monotonic

from fleetmind.observability import CORRELATION

INPUT_TOPIC = "fleetmind.telemetry.v1"
DEAD_LETTER_TOPIC = "fleetmind.telemetry.dlq.v1"
GROUP = "fleetmind-inference-v1"
DELIVERY_TIMEOUT = 6


class BrokerFailure(RuntimeError):
    """A broker operation did not establish the requested outcome."""


def kafka():
    try:
        return importlib.import_module("confluent_kafka")
    except ImportError:
        raise BrokerFailure(
            "Install requirements-telemetry.txt to use Kafka."
        ) from None


def report(kind, **fields):
    report = {
        "kind": kind,
        "operation": kind,
        "timestamp": datetime.now(UTC).isoformat(),
        "correlation_id": CORRELATION.get(),
        **fields,
    }
    print(json.dumps(report, separators=(",", ":")), flush=True)


@dataclass(frozen=True)
class BrokerSettings:
    bootstrap: str
    topic: str = INPUT_TOPIC
    dead_letter_topic: str = DEAD_LETTER_TOPIC
    group: str = GROUP

    def __post_init__(self):
        for name in (self.topic, self.dead_letter_topic, self.group):
            if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,199}", name):
                raise ValueError("Topic and group names must be 1–200 safe characters.")
        if self.topic == self.dead_letter_topic:
            raise ValueError("The input and dead-letter topics must be different.")
        if not self.bootstrap.strip():
            raise ValueError("Bootstrap servers are required.")

    @staticmethod
    def add_arguments(parser):
        parser.add_argument(
            "--bootstrap",
            default=os.getenv(
                "FLEETMIND_KAFKA_BOOTSTRAP_SERVERS",
                "127.0.0.1:19092",
            ),
        )
        parser.add_argument(
            "--topic", default=os.getenv("FLEETMIND_TELEMETRY_TOPIC", INPUT_TOPIC)
        )
        parser.add_argument(
            "--dead-letter-topic",
            default=os.getenv(
                "FLEETMIND_TELEMETRY_DLQ",
                DEAD_LETTER_TOPIC,
            ),
        )
        parser.add_argument(
            "--group", default=os.getenv("FLEETMIND_TELEMETRY_GROUP", GROUP)
        )

    @classmethod
    def from_args(cls, args):
        return cls(args.bootstrap, args.topic, args.dead_letter_topic, args.group)


def install_stop_handlers(stop: Event):
    def stop_requested(_signum, _frame):
        stop.set()

    signal.signal(signal.SIGINT, stop_requested)
    signal.signal(signal.SIGTERM, stop_requested)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, stop_requested)


def ensure_topics(settings: BrokerSettings, partitions: int = 3):
    client = kafka()
    admin = importlib.import_module("confluent_kafka.admin")
    cluster = admin.AdminClient({"bootstrap.servers": settings.bootstrap})
    topics = [
        admin.NewTopic(settings.topic, num_partitions=partitions, replication_factor=1),
        admin.NewTopic(
            settings.dead_letter_topic, num_partitions=1, replication_factor=1
        ),
    ]
    try:
        for future in cluster.create_topics(topics, request_timeout=10).values():
            try:
                future.result()
            except client.KafkaException as exc:
                if exc.args[0].code() != client.KafkaError.TOPIC_ALREADY_EXISTS:
                    raise
    except (client.KafkaException, TimeoutError):
        raise BrokerFailure("Could not provision telemetry topics.") from None


class Publisher:
    def __init__(self, settings: BrokerSettings):
        self.producer = kafka().Producer(
            {
                "bootstrap.servers": settings.bootstrap,
                "enable.idempotence": True,
                "acks": "all",
                "message.send.max.retries": 2,
                "delivery.timeout.ms": 5000,
                "request.timeout.ms": 3000,
                "linger.ms": 0,
                "partitioner": "murmur2_random",
                "allow.auto.create.topics": False,
            }
        )

    def publish(self, topic: str, key: str, payload: bytes):
        result = []

        def acknowledged(error, message):
            result.append((error, message))

        try:
            self.producer.produce(
                topic, key=key, value=payload, on_delivery=acknowledged
            )
            pending = self.producer.flush(DELIVERY_TIMEOUT)
        except (BufferError, kafka().KafkaException):
            raise BrokerFailure(
                "Publish failed before delivery was confirmed."
            ) from None
        if pending or not result or result[0][0] is not None:
            raise BrokerFailure("Broker delivery was not confirmed.")
        return result[0][1]


class ConsumerLag:
    """Read librdkafka's committed lag samples without polling the broker."""

    def __init__(self, topic: str):
        self.topic = topic
        self.clear()

    def clear(self):
        self.value: int | None = None
        self.sampled_at = 0.0

    def update(self, raw: str):
        try:
            stats = json.loads(raw)
        except ValueError:
            self.clear()
            return
        partitions = stats.get("topics", {}).get(self.topic, {}).get("partitions", {})
        expected = stats.get("cgrp", {}).get("assignment_size", 0)
        lag = []
        for part in partitions.values():
            if part.get("fetch_state") != "active":
                continue
            reported = part.get("consumer_lag", -1)
            if reported < 0:
                low, high = part.get("lo_offset", -1), part.get("hi_offset", -1)
                reported = 0 if high == 0 or (high >= 0 and high == low) else -1
            lag.append(reported)
        self.value = (
            sum(lag) if expected and len(lag) == expected and min(lag) >= 0 else None
        )
        self.sampled_at = monotonic()

    def read(self):
        return self.value if monotonic() - self.sampled_at < 3 else None


def create_consumer(
    settings: BrokerSettings,
    emit: Callable = report,
    *,
    lag: ConsumerLag | None = None,
):
    client = kafka()
    consumer = client.Consumer(
        {
            "bootstrap.servers": settings.bootstrap,
            "group.id": settings.group,
            "enable.auto.commit": False,
            "enable.auto.offset.store": False,
            "auto.offset.reset": "earliest",
            "allow.auto.create.topics": False,
            "max.poll.interval.ms": 120_000,
            "socket.timeout.ms": 8_000,
            **({"statistics.interval.ms": 500, "stats_cb": lag.update} if lag else {}),
        }
    )

    def rebalance(kind):
        def callback(_consumer, partitions):
            if lag:
                lag.clear()
            emit(kind, partitions=[part.partition for part in partitions])

        return callback

    consumer.subscribe(
        [settings.topic],
        on_assign=rebalance("assigned"),
        on_revoke=rebalance("revoked"),
        on_lost=rebalance("lost"),
    )
    return consumer
