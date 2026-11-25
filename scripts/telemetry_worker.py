"""Run the independent telemetry inference worker or provision its topics."""

import argparse
from threading import Event

from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from fleetmind.db.database import DATABASE_URL
from fleetmind.observability import (
    configure_logging,
    configure_tracing,
    stop_tracing,
    worker_scrape,
)
from fleetmind.services.predictions import load_frozen_model
from fleetmind.telemetry.broker import (
    BrokerFailure,
    BrokerSettings,
    ConsumerLag,
    Publisher,
    create_consumer,
    ensure_topics,
    install_stop_handlers,
    kafka,
    report,
)
from fleetmind.telemetry.reporting import WorkerReporter
from fleetmind.telemetry.storage import TelemetryAssessment, TelemetryStore
from fleetmind.telemetry.worker import TelemetryWorker, WorkerHalt


def worker_engine(url=DATABASE_URL, *, pool_size=1):
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=0,
        pool_timeout=5,
        connect_args={
            "connect_timeout": 4,
            "options": "-c statement_timeout=5000 -c lock_timeout=3000",
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    BrokerSettings.add_arguments(parser)
    parser.add_argument(
        "--create-topics", action="store_true", help="Provision topics and exit"
    )
    parser.add_argument("--partitions", type=int, default=3)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--max-events", type=int)
    parser.add_argument("--trace", action="store_true")
    parser.add_argument(
        "--metrics-port", type=int, help="Optional loopback Prometheus port"
    )
    parser.add_argument("--report-interval", type=float, default=5)
    args = parser.parse_args()
    if not 1 <= args.partitions <= 32 or not 0 <= args.retries <= 5:
        parser.error("Use 1–32 partitions and 0–5 database retries.")
    if args.max_events is not None and args.max_events < 1:
        parser.error("--max-events must be positive.")
    if args.metrics_port is not None and not 1024 <= args.metrics_port <= 65535:
        parser.error("--metrics-port must be between 1024 and 65535.")
    if not 0.2 <= args.report_interval <= 300:
        parser.error("--report-interval must be 0.2–300 seconds.")
    try:
        settings = BrokerSettings.from_args(args)
        client = kafka()
    except (ValueError, BrokerFailure) as exc:
        parser.exit(1, f"{exc}\n")
    if args.create_topics:
        try:
            ensure_topics(settings, args.partitions)
        except BrokerFailure as exc:
            parser.exit(1, f"{exc}\n")
        report(
            "topics_ready", input=settings.topic, dead_letter=settings.dead_letter_topic
        )
        return 0
    stop = Event()
    install_stop_handlers(stop)
    engine = worker_engine()
    configure_logging()
    tracing = configure_tracing("fleetmind-worker")
    metrics_engine = None
    reporter = None
    try:
        with engine.connect() as db:
            db.execute(select(TelemetryAssessment.event_id).limit(1))
        model = load_frozen_model()
        metrics_engine = worker_engine()
        reporter = WorkerReporter(
            sessionmaker(bind=metrics_engine), settings.bootstrap, settings.topic
        )
        lag = ConsumerLag(settings.topic)
        worker = TelemetryWorker(
            create_consumer(settings, lag=lag),
            Publisher(settings),
            TelemetryStore(sessionmaker(bind=engine), model),
            settings,
            stop,
            retries=args.retries,
            trace=args.trace,
            read_lag=lag.read,
            submit_metrics=reporter.submit,
        )
        with worker_scrape(args.metrics_port):
            worker.run(args.max_events, args.report_interval)
    except (OSError, ValueError) as exc:
        report(
            "worker_failed",
            reason="runtime_configuration",
            error_type=type(exc).__name__,
        )
        return 1
    except SQLAlchemyError as exc:
        report(
            "worker_failed",
            reason="database_unavailable",
            error_type=type(exc).__name__,
        )
        return 1
    except WorkerHalt as exc:
        report("worker_halted", reason=str(exc))
        return 0 if stop.is_set() else 1
    except (BrokerFailure, client.KafkaException) as exc:
        report(
            "worker_failed", reason="broker_operation", error_type=type(exc).__name__
        )
        return 1
    finally:
        if reporter is not None:
            reporter.close()
        if metrics_engine is not None:
            metrics_engine.dispose()
        engine.dispose()
        stop_tracing(tracing)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
