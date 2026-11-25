"""Measure local telemetry delivery on explicitly disposable infrastructure."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import monotonic, sleep
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from fleetmind.db.models import Asset
from fleetmind.telemetry.broker import BrokerSettings, Publisher, ensure_topics, kafka
from scripts.produce_telemetry import run_simulation
from scripts.telemetry_worker import worker_engine


def sample_resources(pid, stop, samples):
    try:
        import psutil
    except ImportError:
        return
    try:
        parent = psutil.Process(pid)
        while not stop.is_set():
            processes = [parent, *parent.children(recursive=True)]
            rss = cpu = 0
            for process in processes:
                try:
                    with process.oneshot():
                        rss += process.memory_info().rss
                        usage = process.cpu_times()
                        cpu += usage.user + usage.system
                except psutil.Error:
                    continue
            samples.append((rss, cpu))
            stop.wait(0.1)
    except psutil.Error:
        return


def read_events(path):
    output = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            output.append(json.loads(line))
        except ValueError:
            continue
    return [event for event in output if isinstance(event, dict) and "kind" in event]


def wait_for_assignment(process, log_path):
    deadline = monotonic() + 35
    while monotonic() < deadline and process.poll() is None:
        if any(event["kind"] == "assigned" for event in read_events(log_path)):
            return
        sleep(0.1)
    raise RuntimeError(
        "Worker did not get an assignment. Check its logs and infrastructure."
    )


def final_lag(settings):
    client = kafka()
    reader = client.Consumer(
        {
            "bootstrap.servers": settings.bootstrap,
            "group.id": settings.group,
            "enable.auto.commit": False,
            "allow.auto.create.topics": False,
        }
    )
    try:
        topic = reader.list_topics(settings.topic, timeout=3).topics[settings.topic]
        assigned = [client.TopicPartition(settings.topic, p) for p in topic.partitions]
        offsets = reader.committed(assigned, timeout=3)
        if not offsets or any(part.error is not None for part in offsets):
            return None
        total = 0
        for part in offsets:
            low, high = reader.get_watermark_offsets(part, timeout=3)
            if low < 0 or high < 0:
                return None
            total += max(0, high - max(low, part.offset))
        return total
    except (client.KafkaException, KeyError):
        return None
    finally:
        reader.close()


def run_case(url, bootstrap, prefix, assets, *, label, rate, count):
    settings = BrokerSettings(
        bootstrap,
        f"{prefix}.{label}",
        f"{prefix}.{label}.dlq",
        f"{prefix}.{label}",
    )
    ensure_topics(settings)
    publisher = Publisher(settings)
    args = [
        sys.executable,
        "-m",
        "scripts.telemetry_worker",
        "--bootstrap",
        bootstrap,
        "--topic",
        settings.topic,
        "--dead-letter-topic",
        settings.dead_letter_topic,
        "--group",
        settings.group,
        "--max-events",
        str(count),
        "--trace",
        "--report-interval",
        "0.25",
    ]
    samples = []
    with TemporaryDirectory(prefix="fleetmind-telemetry-") as scratch:
        path = Path(scratch) / "worker.jsonl"
        with path.open("wb", buffering=0) as log:
            process = subprocess.Popen(
                args,
                stdout=log,
                stderr=subprocess.STDOUT,
                env={**os.environ, "DATABASE_URL": url},
            )
            stop = Event()
            sampler = Thread(target=sample_resources, args=(process.pid, stop, samples))
            sampler.start()
            try:
                wait_for_assignment(process, path)
                started = monotonic()
                producer = run_simulation(
                    publisher,
                    settings,
                    assets,
                    Event(),
                    rate=rate,
                    count=count,
                    duration=None,
                    seed=42,
                    scenario="normal",
                )
                if producer["acknowledged"] != count:
                    raise RuntimeError(
                        "The benchmark publisher did not acknowledge every event."
                    )
                if process.wait(timeout=60) != 0:
                    raise RuntimeError("The benchmark worker exited unsuccessfully.")
                worker_events = read_events(path)
            finally:
                stop.set()
                sampler.join(timeout=2)
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)
    stats = next(event for event in worker_events if event["kind"] == "worker_stopped")
    completions = [event for event in worker_events if event["kind"] == "event_handled"]
    if stats["processed"] != count or len(completions) != count:
        raise RuntimeError(
            "The worker did not persist the expected number of assessments."
        )
    reported_lags = [
        event["assigned_committed_lag"]
        for event in worker_events
        if event.get("assigned_committed_lag") is not None
    ]
    finished = max(event["handled_monotonic_s"] for event in completions)
    return {
        "case": label,
        "target_events_per_s": rate or None,
        "events": count,
        "producer_acknowledged_per_s": producer["acknowledged_per_s"],
        "consumer_committed_per_s": round(count / (finished - started), 3),
        "sampled_peak_lag": max(reported_lags, default=None),
        "final_committed_lag": final_lag(settings),
        "latency_ms": stats["latency"],
        "processed": stats["processed"],
        "duplicates": stats["duplicates"],
        "dead_lettered": stats["dead_lettered"],
        "worker_peak_rss_mib": round(max(rss for rss, _ in samples) / 2**20, 2)
        if samples
        else None,
        "worker_cpu_s_sampled": round(max(cpu for _, cpu in samples), 3)
        if samples
        else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--disposable", action="store_true", required=True)
    parser.add_argument("--bootstrap", default="127.0.0.1:19092")
    parser.add_argument("--seconds", type=int, default=5)
    parser.add_argument("--burst", type=int, default=250)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 2 <= args.seconds <= 30 or not 1 <= args.burst <= 2000:
        parser.error("Use 2–30 seconds per rate and a burst of 1–2000 events.")
    url = os.getenv("FLEETMIND_TELEMETRY_TEST_DATABASE_URL")
    if not url:
        parser.error(
            "Set FLEETMIND_TELEMETRY_TEST_DATABASE_URL to a disposable database "
            "migrated to head."
        )
    prefix = f"fleetmind-bench-{uuid4().hex[:12]}"
    assets = [(f"{prefix}-{kind.lower()}", kind) for kind in ("L", "M", "H")]
    engine = worker_engine(url)
    try:
        with Session(engine) as db, db.begin():
            name = db.scalar(text("SELECT current_database()"))
            if not name.startswith("fleetmind_") or not name.endswith("_test"):
                parser.error("Use a disposable database named fleetmind_*_test.")
            db.execute(select(Asset.asset_id).limit(1))
            db.add_all(
                Asset(
                    asset_id=asset_id, display_name="Benchmark asset", machine_type=kind
                )
                for asset_id, kind in assets
            )
        cases = [
            run_case(
                url,
                args.bootstrap,
                prefix,
                assets,
                label=f"rate-{rate}",
                rate=rate,
                count=rate * args.seconds,
            )
            for rate in (1, 10, 50)
        ]
        cases.append(
            run_case(
                url,
                args.bootstrap,
                prefix,
                assets,
                label="burst",
                rate=0,
                count=args.burst,
            )
        )
        payload = json.dumps(
            {"seconds_per_rate": args.seconds, "cases": cases}, indent=2
        )
        print(payload)
        if args.output:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(payload + "\n")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
