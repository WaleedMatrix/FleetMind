"""Validate a local public inference container against the recorded fixture."""

import argparse
import json
import statistics
from pathlib import Path
from time import perf_counter
from urllib.error import HTTPError
from urllib.request import Request, urlopen

SENSORS = (
    "machine_type",
    "air_temperature_k",
    "process_temperature_k",
    "rotational_speed_rpm",
    "torque_nm",
    "tool_wear_min",
)


def infer(origin, reading):
    before = perf_counter()
    request = Request(
        f"{origin}/infer",
        data=json.dumps(reading).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=20) as response:
        data = json.load(response)
    return data, (perf_counter() - before) * 1000


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=19983)
    parser.add_argument("--output", type=Path)
    options = parser.parse_args()
    origin = f"http://127.0.0.1:{options.port}"
    source = Path("frontend/src/data/portfolio.json").read_text(encoding="utf-8")
    rows = json.loads(source)["predictions"][::5]
    # Reserve the final permitted attempt for the rate-limit boundary check.
    rows = rows[:29]
    timings, differences = [], []
    for sample in rows:
        reading = {key: sample[key] for key in SENSORS}
        result, elapsed = infer(origin, reading)
        for key in ("model_version", "alert_level", "predicted_failure"):
            if result[key] != sample[key]:
                raise ValueError(f"Model outcome differs for {key}.")
        timings.append(elapsed)
        differences.append(abs(result["failure_score"] - sample["failure_score"]))
    if max(differences) > 1e-6:
        raise ValueError("CPU inference and frozen fixture scores differ.")
    result = {
        "loopback_request_count": len(rows),
        "maximum_absolute_score_difference": max(differences),
        "latency_ms": {
            "p50": round(statistics.median(timings), 2),
            "p95": round(
                statistics.quantiles(timings, n=20, method="inclusive")[-1], 2
            ),
            "max": round(max(timings), 2),
        },
    }
    infer(origin, reading)
    try:
        infer(origin, reading)
    except HTTPError as error:
        if error.code != 429 or not error.headers.get("Retry-After"):
            raise
        result["shared_rate_limit_http_status"] = error.code
    else:
        raise ValueError("Expected the shared demo limit to return HTTP 429.")
    report = json.dumps(result, indent=2) + "\n"
    if options.output:
        with options.output.open("x", encoding="utf-8") as stream:
            stream.write(report)
    print(report, end="")


if __name__ == "__main__":
    main()
