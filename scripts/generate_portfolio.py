"""Build sanitized portfolio fixtures from a seeded simulator and frozen model."""

import asyncio
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from random import Random
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from fleetmind.api.model_intelligence import explain_record, load_model_intelligence
from fleetmind.api.schemas import (
    AssetResponse,
    MachineReading,
    PredictionHistoryResponse,
    ReadingSource,
)
from fleetmind.artifacts import MODEL_PATH, PROJECT_ROOT, verify_artifacts
from fleetmind.config import MODEL_VERSION
from fleetmind.copilot.orchestration import Orchestrator
from fleetmind.copilot.settings import Settings
from fleetmind.db.models import Asset, PredictionHistory
from fleetmind.explainability import ModelExplainer
from fleetmind.model_monitoring import model_health, read_reference
from fleetmind.services.predictions import assess, load_frozen_model
from scripts.copilot_fixtures import (
    FixtureEnvironment,
    FixtureToolExecutor,
    ScriptedProvider,
)
from scripts.evaluate_copilot import payload
from scripts.simulate_sensors import generate_reading

SEED = 241
N = 144
START = datetime(2026, 1, 12, 8, tzinfo=UTC)
END = START + timedelta(minutes=21 * N)
SOURCES: tuple[ReadingSource, ...] = ("simulated", "telemetry", "manual", "unknown")
ASSETS = (
    ("demo-press", "Forming press", "L", "Demo · Forming cell"),
    ("demo-spindle", "Spindle station", "M", "Demo · Machining cell"),
    ("demo-pump", "Circulation pump", "H", "Demo · Utilities"),
    ("demo-mill", "Finishing mill", "M", "Demo · Finishing cell"),
)


def json_file(path):
    return json.loads((PROJECT_ROOT / path).read_text(encoding="utf-8"))


def aggregate(rows):
    return {
        "total_predictions": len(rows),
        "high_priority_alerts": sum(
            row["alert_level"] == "high_priority" for row in rows
        ),
        "review_alerts": sum(row["alert_level"] == "review" for row in rows),
        "no_alert_predictions": sum(row["alert_level"] == "no_alert" for row in rows),
        "average_failure_score": (
            sum(row["failure_score"] for row in rows) / len(rows) if rows else None
        ),
    }


def trends(rows, interval):
    groups = defaultdict(list)
    for row in rows:
        observed = datetime.fromisoformat(row["created_at"])
        hour = observed.hour if interval == "hour" else 0
        timestamp = observed.replace(hour=hour, minute=0, second=0, microsecond=0)
        groups[timestamp.isoformat()].append(row)
    return {
        "interval": interval,
        "points": [
            {"timestamp": stamp, **aggregate(items)}
            for stamp, items in sorted(groups.items())
        ],
    }


async def examples():
    fixtures = FixtureEnvironment()
    rows = []
    try:
        for case in json_file("docs/copilot/evaluation.json"):
            if case["id"] not in {"k01", "k05", "k07", "o02"}:
                continue
            request = payload(case)
            answer = await Orchestrator(
                ScriptedProvider(case),
                FixtureToolExecutor(fixtures.store, fixtures.hits, case),
                Settings(provider="mock"),
            ).chat(request, fixtures.context(request))
            if answer.status != case["status"]:
                raise ValueError(f"Recorded example did not satisfy case {case['id']}.")
            rows.append(
                {
                    "id": case["id"],
                    "question": request.question,
                    "status": answer.status,
                    "answer": answer.answer,
                    "citations": [
                        citation.model_dump(mode="json")
                        for citation in answer.citations
                    ],
                }
            )
        return rows
    finally:
        fixtures.engine.dispose()


def build():
    hashes = verify_artifacts()
    model = load_frozen_model()
    explainer = ModelExplainer(model, MODEL_VERSION)
    reference = read_reference()
    intelligence = load_model_intelligence(
        PROJECT_ROOT, MODEL_PATH, MODEL_VERSION, explainer
    )
    if intelligence is None or intelligence.evaluation is None:
        raise ValueError("Frozen model evaluation is required.")
    engine = create_engine("sqlite://")
    Asset.metadata.create_all(
        engine, tables=[Asset.__table__, PredictionHistory.__table__]
    )
    rows, outputs, assets = [], {}, []
    rng = Random(SEED)
    try:
        with Session(engine) as db:
            for key, name, kind, area in ASSETS:
                asset = Asset(
                    asset_id=key,
                    display_name=name,
                    machine_type=kind,
                    location=area,
                    created_at=START,
                    description="Fictional asset for the portfolio dataset.",
                )
                db.add(asset)
                assets.append(
                    AssetResponse.model_validate(asset).model_dump(mode="json")
                )
            db.flush()
            for i in range(N):
                asset_id, _, kind, _ = ASSETS[i % len(ASSETS)]
                scenario = "stress" if i % 9 < 3 else "normal"
                raw = generate_reading(rng, scenario)
                raw.pop("source")
                reading = MachineReading.model_validate({**raw, "machine_type": kind})
                row = assess(db, model, reading, asset_id=asset_id, source="simulated")
                row.id = i + 1
                row.created_at = START + timedelta(minutes=i * 21)
                result = PredictionHistoryResponse.model_validate(row).model_dump(
                    mode="json"
                )
                rows.append(result)
                outputs[str(row.id)] = explain_record(
                    row,
                    MODEL_VERSION,
                    explainer,
                ).model_dump(mode="json")
            db.flush()
            health = {
                f"{source}:{hours}": model_health(
                    db, reference, source, hours, now=END
                ).model_dump(mode="json")
                for source in SOURCES
                for hours in (24, 168, 720)
            }
    finally:
        engine.dispose()
    cases = json_file("reports/telemetry_worker_scaling_m11b.json")["cases"]
    browser_before = json_file("reports/browser_m11b_baseline.json")["telemetry"]
    browser_after = json_file("reports/browser_m11b_candidate.json")["telemetry"]
    return {
        "provenance": {
            "seed": SEED,
            "recorded_through": END.isoformat(),
            "artifact_hashes": hashes,
        },
        "assets": assets,
        "predictions": rows,
        "explanations": outputs,
        "summaries": {
            asset["asset_id"]: aggregate(
                [row for row in rows if row["asset_id"] == asset["asset_id"]]
            )
            for asset in assets
        },
        "summary": aggregate(rows),
        "trends": {interval: trends(rows, interval) for interval in ("hour", "day")},
        "intelligence": intelligence.model_dump(mode="json"),
        "modelHealth": health,
        "telemetryIds": [
            str(uuid5(NAMESPACE_URL, f"fleetmind-portfolio/{row['prediction_id']}"))
            for row in rows
        ],
        "copilot": asyncio.run(examples()),
        "performance": {
            "workers": [
                {
                    "workers": case["workers"],
                    "events": case["events"],
                    "commits_per_s": case["consumer_events_per_second"],
                    "p95_s": case["latency_ms"]["observation_to_commit_ms"]["p95"]
                    / 1000,
                }
                for case in cases
                if case["target_events_per_second"] == 60
            ],
            "longTasks": [
                browser_before["long_task_count"],
                browser_after["long_task_count"],
            ],
            "heapMiB": [browser_before["js_heap_mib"], browser_after["js_heap_mib"]],
        },
    }


def main():
    output = Path("frontend/src/data/portfolio.json")
    output.parent.mkdir(exist_ok=True, parents=True)
    data = build()
    output.write_text(
        json.dumps(data, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"Generated {len(data['predictions'])} simulated assessments "
        "and SHAP explanations."
    )


if __name__ == "__main__":
    main()
