import json
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from fleetmind.api.inference import classify_alert, to_model_frame
from fleetmind.api.schemas import MachineReading
from fleetmind.config import MODEL_VERSION
from fleetmind.db.models import Asset, PredictionHistory
from fleetmind.model_monitoring import (
    MIN_OBSERVATIONS,
    Reference,
    bins,
    compare,
    hash_file,
    model_health,
    quantile_edges,
    read_reference,
)
from fleetmind.services.predictions import MODEL_PATH, assess, load_frozen_model


def test_reference_is_bound_to_the_frozen_artifacts(tmp_path):
    reference = read_reference()
    assert reference.sample_size == 8000
    assert reference.model_sha256 == hash_file(MODEL_PATH)
    raw = reference.model_dump(mode="json")
    raw["histograms"][0]["counts"][0] += 1
    raw["histograms"][0]["counts"][1] -= 1
    with pytest.raises(ValidationError, match="fingerprint mismatch"):
        Reference.model_validate(raw)
    path = tmp_path / "copied-reference.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValidationError):
        read_reference(path)


def test_histograms_include_open_tails_and_smoothing_is_finite():
    assert bins([-100, 0, 2, 100], [0, 2]) == [1, 1, 2]
    assert quantile_edges(np.array([1] * 9 + [2])) == pytest.approx([1.1])
    for categorical in (False, True):
        same, _, _ = compare([10, 0, 10], [10, 0, 10], categorical=categorical)
        shifted, _, severe = compare([150, 0, 0], [0, 0, 150], categorical=categorical)
        assert same == 0 and np.isfinite(shifted) and shifted > severe


def test_observations_are_source_time_and_model_scoped(monkeypatch):
    engine = create_engine("sqlite://")
    Asset.metadata.create_all(
        engine, tables=[Asset.__table__, PredictionHistory.__table__]
    )
    now = datetime.now(UTC)
    reference = read_reference()
    reading = {
        "machine_type": "M",
        "air_temperature_k": 299,
        "process_temperature_k": 311,
        "torque_nm": 39,
        "rotational_speed_rpm": 1490,
        "tool_wear_min": 21,
        "failure_score": 0.1,
        "predicted_failure": False,
        "alert_level": "no_alert",
    }
    with Session(engine) as db:
        for source, version, created, count in [
            ("telemetry", MODEL_VERSION, now - timedelta(hours=1), MIN_OBSERVATIONS),
            ("simulated", MODEL_VERSION, now, 1),
            ("telemetry", MODEL_VERSION, now - timedelta(days=10), 1),
            ("telemetry", "other", now, 1),
        ]:
            db.add_all(
                PredictionHistory(
                    source=source,
                    model_version=version,
                    created_at=created,
                    **reading,
                )
                for _ in range(count)
            )
        db.commit()

        current = model_health(db, reference, "telemetry", 24, now=now)
        assert current.state == "ready" and current.observations == MIN_OBSERVATIONS
        assert len(current.comparisons) == 9
        assert all(
            sum(plot.observed_counts) == current.observations
            for plot in current.comparisons
        )
        simulated = model_health(db, reference, "simulated", 24, now=now)
        assert simulated.state == "insufficient_data" and simulated.observations == 1
        assert all(
            plot.value is None and plot.indicator is None
            for plot in simulated.comparisons
        )
        assert model_health(db, None, "telemetry", 24, now=now).state == "unavailable"
        monkeypatch.setattr("fleetmind.model_monitoring.MAX_OBSERVATIONS", 10)
        clipped = model_health(db, reference, "telemetry", 24, now=now)
        assert clipped.observations == 10 and clipped.truncated
    engine.dispose()


def test_instrumented_inference_reproduces_frozen_pipeline_scores():
    class Staging:
        def add(self, _record):
            pass

    model = load_frozen_model()
    for kind, wear in (("L", 100), ("M", 220), ("H", 0)):
        reading = MachineReading(
            machine_type=kind,
            air_temperature_k=299,
            process_temperature_k=312,
            rotational_speed_rpm=1420,
            torque_nm=42,
            tool_wear_min=wear,
        )
        expected = float(model.predict_proba(to_model_frame(reading))[0, 1])
        actual = assess(Staging(), model, reading, asset_id=None, source="simulated")
        assert (actual.failure_score, actual.alert_level) == (
            expected,
            classify_alert(expected),
        )
