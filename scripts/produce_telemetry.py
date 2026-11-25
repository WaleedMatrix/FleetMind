"""Publish seeded synthetic telemetry for registered FleetMind assets."""

import argparse
import math
import random
from datetime import UTC, datetime
from threading import Event
from time import monotonic
from uuid import uuid4

from fleetmind.db.database import SessionLocal
from fleetmind.db.models import Asset
from fleetmind.telemetry.broker import (
    BrokerFailure,
    BrokerSettings,
    Publisher,
    install_stop_handlers,
    report,
)
from fleetmind.telemetry.contracts import TelemetryEvent
from scripts.simulate_sensors import generate_reading


def simulate_event(rng, scenario, asset_id, machine_type):
    reading = generate_reading(rng, scenario)
    reading["machine_type"] = machine_type
    return TelemetryEvent(
        event_id=uuid4(),
        schema_version=1,
        asset_id=asset_id,
        observed_at=datetime.now(UTC),
        **reading,
    )


def run_simulation(
    publisher, settings, assets, stop, *, rate, count, duration, seed, scenario
):
    rng = random.Random(seed)
    started = monotonic()
    attempted = delivered = failed = 0
    while not stop.is_set() and (count is None or attempted < count):
        elapsed = monotonic() - started
        next_at = attempted / rate if rate else elapsed
        if duration is not None and max(next_at, elapsed) >= duration:
            break
        if stop.wait(max(0, next_at - elapsed)):
            break
        if duration is not None and monotonic() - started >= duration:
            break
        asset_id, machine_type = assets[attempted % len(assets)]
        event = simulate_event(rng, scenario, asset_id, machine_type)
        attempted += 1
        try:
            publisher.publish(
                settings.topic, asset_id, event.model_dump_json().encode()
            )
        except BrokerFailure:
            failed += 1
            break
        delivered += 1
    elapsed = monotonic() - started
    return {
        "source": "simulated",
        "scenario": scenario,
        "seed": seed,
        "attempted": attempted,
        "acknowledged": delivered,
        "unconfirmed": failed,
        "elapsed_s": round(elapsed, 3),
        "acknowledged_per_s": round(delivered / elapsed, 3),
        "interrupted": stop.is_set(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    BrokerSettings.add_arguments(parser)
    parser.add_argument(
        "--asset", action="append", required=True, help="Repeat for multiple asset IDs"
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=1,
        help="Events per second, or 0 for a bounded burst",
    )
    parser.add_argument("--count", type=int)
    parser.add_argument(
        "--duration", type=float, help="Maximum run duration in seconds"
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--scenario", choices=["normal", "stress"], default="normal")
    args = parser.parse_args()
    if not 0 <= args.rate <= 10_000:
        parser.error("--rate must be 0–10000.")
    if args.count is not None and not 1 <= args.count <= 100_000:
        parser.error("--count must be 1–100000.")
    if args.duration is not None and (
        not math.isfinite(args.duration) or args.duration <= 0
    ):
        parser.error("--duration must be finite and positive.")
    if args.count is None and args.duration is None:
        args.count = 20
    with SessionLocal() as db:
        assets = []
        for asset_id in dict.fromkeys(args.asset):
            asset = db.get(Asset, asset_id)
            if asset is None:
                parser.error(f"Register asset {asset_id!r} before publishing.")
            assets.append((asset.asset_id, asset.machine_type))
    stop = Event()
    install_stop_handlers(stop)
    try:
        settings = BrokerSettings.from_args(args)
        summary = run_simulation(
            Publisher(settings),
            settings,
            assets,
            stop,
            rate=args.rate,
            count=args.count,
            duration=args.duration,
            seed=args.seed,
            scenario=args.scenario,
        )
    except (BrokerFailure, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    report("producer_summary", **summary)
    return int(bool(summary["unconfirmed"]))


if __name__ == "__main__":
    raise SystemExit(main())
