"""Benchmark one and several sequential consumers in isolated Kafka groups."""

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
from contextlib import ExitStack, suppress
from pathlib import Path
from secrets import token_urlsafe
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import monotonic, sleep
from uuid import uuid4

import httpx
from prometheus_client.parser import text_string_to_metric_families
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from fleetmind.db.models import Asset, PredictionHistory
from fleetmind.telemetry.broker import BrokerSettings, Publisher, ensure_topics
from fleetmind.telemetry.worker import latency_summary
from scripts.benchmark_telemetry import (
    final_lag,
    read_events,
    sample_resources,
    wait_for_assignment,
)
from scripts.produce_telemetry import run_simulation
from scripts.telemetry_worker import worker_engine

AUDITED_PHASES = {
    "feature_preparation",
    "model_inference",
    "telemetry_database",
    "telemetry_transaction",
    "offset_acknowledgement",
    "kafka_poll",
    "telemetry_serialization",
    "telemetry_decode",
    "worker_pool_checkout",
    "telemetry_delivery",
}


def unused_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def collect_phases(ports, token):
    results = {}
    for port in ports:
        response = httpx.get(
            f"http://127.0.0.1:{port}/metrics",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
            trust_env=False,
        )
        response.raise_for_status()
        for family in text_string_to_metric_families(response.text):
            if family.name != "fleetmind_operation_duration_seconds":
                continue
            for sample in family.samples:
                operation = sample.labels.get("operation")
                if (
                    operation not in AUDITED_PHASES
                    or sample.labels.get("outcome") != "ok"
                ):
                    continue
                if not sample.name.endswith(("_count", "_sum")):
                    continue
                old = results.setdefault(operation, {"count": 0, "sum": 0.0})
                old[sample.name.rsplit("_", 1)[-1]] += sample.value
    return {
        name: {
            "samples": int(data["count"]),
            "mean_ms": 1000 * data["sum"] / data["count"],
        }
        for name, data in sorted(results.items())
        if data["count"]
    }


def stop_worker(process):
    if process.poll() is not None:
        return
    try:
        process.send_signal(
            signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM
        )
        process.wait(timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        with suppress(OSError):
            process.terminate()
        process.wait(timeout=8)


def run_case(url, bootstrap, prefix, assets, *, workers, partitions, rate, count):
    label = f"{workers}w-{rate or 'burst'}"
    topic = f"{prefix}.{label}"
    config = BrokerSettings(bootstrap, topic, topic + ".dlq", topic)
    ensure_topics(config, partitions)
    with (
        TemporaryDirectory(prefix="fleetmind-scaling-") as directory,
        ExitStack() as on_exit,
    ):
        scratch = Path(directory)
        token = token_urlsafe(32)
        token_file = scratch / "scrape.token"
        token_file.write_text(token, encoding="ascii")
        processes, paths, ports, samplers = [], [], [], []
        for index in range(workers):
            path = scratch / f"worker{index}.jsonl"
            logfile = on_exit.enter_context(path.open("wb", buffering=0))
            port = unused_port()
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "scripts.telemetry_worker",
                    "--bootstrap",
                    bootstrap,
                    "--topic",
                    topic,
                    "--dead-letter-topic",
                    config.dead_letter_topic,
                    "--group",
                    config.group,
                    "--metrics-port",
                    str(port),
                    "--report-interval",
                    "0.5",
                    "--trace",
                ],
                stdout=logfile,
                stderr=subprocess.STDOUT,
                env={
                    **os.environ,
                    "DATABASE_URL": url,
                    "OMP_NUM_THREADS": "1",
                    "FLEETMIND_METRICS_TOKEN_FILE": str(token_file),
                },
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                if os.name == "nt"
                else 0,
            )
            on_exit.callback(stop_worker, process)
            paths.append(path)
            ports.append(port)
            processes.append(process)
        for process, path in zip(processes, paths, strict=True):
            wait_for_assignment(process, path)
        sampling_stop = Event()
        for process in processes:
            samples = []
            thread = Thread(
                target=sample_resources,
                args=(process.pid, sampling_stop, samples),
                daemon=True,
            )
            thread.start()
            samplers.append((thread, samples))
        try:
            started = monotonic()
            produced = run_simulation(
                Publisher(config),
                config,
                assets,
                Event(),
                rate=rate,
                count=count,
                duration=None,
                seed=42,
                scenario="normal",
            )
            if produced["acknowledged"] != count:
                raise RuntimeError("Producer did not acknowledge the full workload.")
            deadline = monotonic() + 60
            while True:
                logs = [read_events(path) for path in paths]
                handled = [
                    [event for event in events if event["kind"] == "event_handled"]
                    for events in logs
                ]
                if sum(map(len, handled)) >= count:
                    break
                if (
                    any(process.poll() is not None for process in processes)
                    or monotonic() >= deadline
                ):
                    raise RuntimeError(
                        "Workers did not acknowledge the complete workload."
                    )
                sleep(0.2)
            phases = collect_phases(ports, token)
        finally:
            sampling_stop.set()
            for thread, _ in samplers:
                thread.join(timeout=2)

        completions = [item for entries in handled for item in entries]
        if len(completions) != count or not all(
            event["outcome"] == "processed" for event in completions
        ):
            raise RuntimeError(
                "Unexpected replay, rejection, or missing persistence in benchmark."
            )
        ids = {item["event_id"] for item in completions}
        if len(ids) != count:
            raise RuntimeError("Repeated event ID in workload.")
        finished = max(event["handled_monotonic_s"] for event in completions)
        latency = {
            field: latency_summary([event[field] for event in completions])
            for field in (
                "inference_ms",
                "database_ms",
                "observation_to_commit_ms",
                "processing_ms",
            )
        }
        lags = [
            item["assigned_committed_lag"]
            for items in logs
            for item in items
            if isinstance(item.get("assigned_committed_lag"), int)
        ]
        resources = [samples for _, samples in samplers if samples]
        return {
            "case": label,
            "workers": workers,
            "partitions": partitions,
            "target_events_per_second": rate or None,
            "events": count,
            "producer_events_per_second": produced["acknowledged_per_s"],
            "consumer_events_per_second": count / (finished - started),
            "wall_seconds_through_last_commit": finished - started,
            "processed_by_worker": [len(batch) for batch in handled],
            "max_sampled_worker_lag": max(lags, default=None),
            "final_group_lag": final_lag(config),
            "latency_ms": latency,
            "phases": phases,
            "sum_of_per_worker_peak_rss_mib": sum(
                max(rss for rss, _ in series) for series in resources
            )
            / 2**20
            if len(resources) == workers
            else None,
            "worker_cpu_seconds_sampled": sum(
                series[-1][1] - series[0][1] for series in resources
            )
            if len(resources) == workers
            else None,
        }


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--disposable", action="store_true", required=True)
    cli.add_argument("--bootstrap", required=True)
    cli.add_argument("--seconds", type=int, default=15)
    cli.add_argument("--rate", type=int, default=60)
    cli.add_argument("--burst", type=int, default=300)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    if not (
        5 <= args.seconds <= 30 and 10 <= args.rate <= 100 and 100 <= args.burst <= 1000
    ):
        cli.error("Use 5–30 seconds, 10–100 events/s, and a 100–1000 event burst.")
    url = os.environ.get("FLEETMIND_TELEMETRY_TEST_DATABASE_URL")
    if not url:
        cli.error("Set FLEETMIND_TELEMETRY_TEST_DATABASE_URL.")
    prefix = f"scale-{uuid4().hex[:12]}"
    assets = [(f"{prefix}-{i}", ("L", "M", "H")[i % 3]) for i in range(24)]
    engine = worker_engine(url)
    try:
        with Session(engine) as db, db.begin():
            database = db.scalar(text("SELECT current_database()"))
            if not database.startswith("fleetmind_") or not database.endswith("_test"):
                cli.error("Expected a disposable fleetmind_*_test database.")
            db.add_all(
                Asset(asset_id=key, display_name="Benchmark fixture", machine_type=kind)
                for key, kind in assets
            )
        cases = [
            run_case(
                url,
                args.bootstrap,
                prefix,
                assets,
                workers=workers,
                partitions=6,
                rate=rate,
                count=count,
            )
            for workers in (1, 2)
            for rate, count in ((args.rate, args.seconds * args.rate), (0, args.burst))
        ]
        with Session(engine) as db:
            count = db.scalar(
                select(func.count())
                .select_from(PredictionHistory)
                .where(
                    PredictionHistory.asset_id.in_([key for key, _ in assets]),
                )
            )
        if count != sum(case["events"] for case in cases):
            raise RuntimeError(
                "Durable prediction count failed to match unique deliveries."
            )
        report = {
            "seconds_requested": args.seconds,
            "durable_predictions": count,
            "cases": cases,
        }
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")
        for case in cases:
            print(
                case["case"],
                f"{case['consumer_events_per_second']:.1f} assessment commits/s",
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
