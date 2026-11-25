"""Shared asset validation, frozen inference, and prediction persistence."""

from datetime import UTC, datetime
from typing import Literal

import joblib
from sqlalchemy.orm import Session

from fleetmind.api.inference import classify_alert, to_model_frame
from fleetmind.api.schemas import MachineReading, ReadingSource
from fleetmind.artifacts import MODEL_PATH as MODEL_PATH
from fleetmind.artifacts import PROJECT_ROOT as PROJECT_ROOT
from fleetmind.artifacts import verify_artifacts
from fleetmind.config import MODEL_VERSION, PRIMARY_THRESHOLD
from fleetmind.db.models import Asset, PredictionHistory
from fleetmind.observability import timed


class AssetValidationError(ValueError):
    def __init__(self, category: Literal["missing_asset", "machine_type_mismatch"]):
        self.category = category


def load_frozen_model():
    verify_artifacts()
    return joblib.load(MODEL_PATH)


def validate_asset(db: Session, asset_id: str | None, reading: MachineReading) -> None:
    if asset_id is None:
        return
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise AssetValidationError("missing_asset")
    if asset.machine_type != reading.machine_type:
        raise AssetValidationError("machine_type_mismatch")


def assess(
    db: Session,
    model,
    reading: MachineReading,
    *,
    asset_id: str | None,
    source: ReadingSource,
) -> PredictionHistory:
    """Stage the frozen-model assessment in the caller's transaction."""
    with timed("feature_preparation"):
        frame = to_model_frame(reading)
    with timed("model_inference"):
        score = float(model.predict_proba(frame)[0, 1])
    record = PredictionHistory(
        **reading.model_dump(include=set(MachineReading.model_fields)),
        asset_id=asset_id,
        source=source,
        failure_score=score,
        predicted_failure=score >= PRIMARY_THRESHOLD,
        alert_level=classify_alert(score),
        model_version=MODEL_VERSION,
        created_at=datetime.now(UTC),
    )
    db.add(record)
    return record
