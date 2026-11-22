"""Generate simulated machine readings for FleetMind.

This script sends synthetic sensor readings to the local
FastAPI prediction endpoint. It does not represent actual
industrial telemetry or confirmed machine failures.
"""

import argparse
import random
import time

import httpx

API_URL = "http://127.0.0.1:8000/api/v1/predict"


def generate_reading(
    rng: random.Random,
    scenario: str,
) -> dict:
    """Generate a plausible synthetic machine reading."""

    machine_type = rng.choice(["L", "M", "H"])

    air_temperature = rng.uniform(295.0, 305.0)
    thermal_gap = rng.uniform(8.0, 12.0)

    if scenario == "stress":
        rotational_speed = rng.uniform(1100.0, 1500.0)
        torque = rng.uniform(50.0, 70.0)
        tool_wear = rng.uniform(180.0, 250.0)
    else:
        rotational_speed = rng.uniform(1400.0, 1900.0)
        torque = rng.uniform(25.0, 50.0)
        tool_wear = rng.uniform(20.0, 170.0)

    return {
        "machine_type": machine_type,
        "air_temperature_k": round(air_temperature, 2),
        "process_temperature_k": round(air_temperature + thermal_gap, 2),
        "rotational_speed_rpm": round(rotational_speed, 2),
        "torque_nm": round(torque, 2),
        "tool_wear_min": round(tool_wear, 2),
    }


def main():
    parser = argparse.ArgumentParser(description="FleetMind synthetic sensor simulator")

    parser.add_argument(
        "--count",
        type=int,
        default=20,
        help="Number of readings to send",
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Seconds between requests",
    )

    parser.add_argument(
        "--scenario",
        choices=["normal", "stress"],
        default="normal",
        help="Sensor generation scenario",
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility",
    )

    args = parser.parse_args()

    if args.count < 1:
        parser.error("--count must be at least 1")

    if args.interval < 0:
        parser.error("--interval cannot be negative")

    rng = random.Random(args.seed)

    print("=== FLEETMIND SENSOR SIMULATOR ===")
    print(f"Scenario: {args.scenario}")
    print(f"Readings: {args.count}")
    print(f"Interval: {args.interval} seconds")
    print()

    successful = 0
    failed = 0
    alert_counts = {
        "no_alert": 0,
        "review": 0,
        "high_priority": 0,
    }

    with httpx.Client(timeout=10.0) as client:
        for index in range(1, args.count + 1):
            reading = generate_reading(
                rng,
                args.scenario,
            )

            try:
                response = client.post(
                    API_URL,
                    json=reading,
                )
                response.raise_for_status()

                prediction = response.json()

                alert_level = prediction["alert_level"]
                alert_counts[alert_level] += 1

                successful += 1

                print(
                    f"[{index}/{args.count}] "
                    f"ID={prediction['prediction_id']} "
                    f"Score={prediction['failure_score']:.4f} "
                    f"Alert={alert_level}"
                )

            except (httpx.HTTPError, ValueError, KeyError) as exc:
                failed += 1
                print(f"[{index}/{args.count}] Request failed: {exc}")

            if index < args.count:
                time.sleep(args.interval)

    print("\n=== SIMULATION SUMMARY ===")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    print(f"No alert: {alert_counts['no_alert']}")
    print(f"Review: {alert_counts['review']}")
    print(f"High priority: {alert_counts['high_priority']}")


if __name__ == "__main__":
    main()
