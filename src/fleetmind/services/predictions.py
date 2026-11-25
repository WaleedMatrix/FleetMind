"""Shared asset validation, frozen inference, and prediction persistence."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import joblib
from sqlalchemy.orm import Session

from fleetmind.api.inference import classify_alert, to_model_frame
from fleetmind.api.schemas import MachineReading, ReadingSource
from fleetmind.config import MODEL_VERSION, PRIMARY_THRESHOLD
from fleetmind.db.models import Asset, PredictionHistory

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODEL_PATH = PROJECT_ROOT / "artifacts" / "models" / f"{MODEL_VERSION}.joblib"


class AssetValidationError(ValueError):
    def __init__(self, category: Literal["missing_asset", "machine_type_mismatch"]):
        self.category = category


def load_frozen_model():
    if not MODEL_PATH.is_file():
        raise FileNotFoundError(f"Model artifact not found: {MODEL_PATH}")
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
    score = float(model.predict_proba(to_model_frame(reading))[0, 1])
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
