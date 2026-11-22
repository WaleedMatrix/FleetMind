"""FleetMind API with PostgreSQL prediction persistence."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import joblib
from fastapi import Depends, FastAPI, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fleetmind.api.inference import (
    classify_alert,
    to_model_frame,
)
from fleetmind.api.schemas import (
    DashboardSummaryResponse,
    MachineReading,
    PredictionHistoryResponse,
    PredictionResponse,
)
from fleetmind.config import MODEL_VERSION, PRIMARY_THRESHOLD
from fleetmind.db.database import get_db
from fleetmind.db.models import PredictionHistory

DBSession = Annotated[Session, Depends(get_db)]

PROJECT_ROOT = Path(__file__).resolve().parents[3]

MODEL_PATH = PROJECT_ROOT / "artifacts" / "models" / f"{MODEL_VERSION}.joblib"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load the frozen model once at application startup."""

    if not MODEL_PATH.is_file():
        raise FileNotFoundError(f"Model artifact not found: {MODEL_PATH}")

    # Load only trusted model artifacts.
    app.state.model = joblib.load(MODEL_PATH)

    print(f"Loaded FleetMind model: {MODEL_VERSION}")

    yield

    del app.state.model


app = FastAPI(
    title="FleetMind API",
    description="Machine failure classification and history API.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
def health(request: Request):
    """Report API readiness."""

    return {
        "status": "ok",
        "model_loaded": hasattr(request.app.state, "model"),
        "model_version": MODEL_VERSION,
    }


@app.post(
    "/api/v1/predict",
    response_model=PredictionResponse,
    status_code=201,
)
def predict(
    reading: MachineReading,
    request: Request,
    db: DBSession,
):
    """Generate and persist a machine failure prediction."""

    model = request.app.state.model
    features = to_model_frame(reading)

    score = float(model.predict_proba(features)[0, 1])

    predicted_failure = score >= PRIMARY_THRESHOLD
    alert_level = classify_alert(score)

    record = PredictionHistory(
        machine_type=reading.machine_type,
        air_temperature_k=reading.air_temperature_k,
        process_temperature_k=reading.process_temperature_k,
        rotational_speed_rpm=reading.rotational_speed_rpm,
        torque_nm=reading.torque_nm,
        tool_wear_min=reading.tool_wear_min,
        failure_score=score,
        predicted_failure=predicted_failure,
        alert_level=alert_level,
        model_version=MODEL_VERSION,
    )

    try:
        db.add(record)
        db.commit()
        db.refresh(record)
    except Exception:
        db.rollback()
        raise

    return PredictionResponse(
        prediction_id=record.id,
        model_version=record.model_version,
        failure_score=record.failure_score,
        predicted_failure=record.predicted_failure,
        alert_level=record.alert_level,
    )


@app.get(
    "/api/v1/predictions",
    response_model=list[PredictionHistoryResponse],
)
@app.get(
    "/api/v1/predictions",
    response_model=list[PredictionHistoryResponse],
)
def list_predictions(
    db: DBSession,
    limit: int = 20,
    offset: int = 0,
    alert_level: str | None = None,
):
    """Return paginated prediction history."""

    if not 1 <= limit <= 100:
        raise HTTPException(
            status_code=422,
            detail="limit must be between 1 and 100",
        )

    if offset < 0:
        raise HTTPException(
            status_code=422,
            detail="offset must be non-negative",
        )

    valid_alerts = {
        "no_alert",
        "review",
        "high_priority",
    }

    if alert_level is not None and alert_level not in valid_alerts:
        raise HTTPException(
            status_code=422,
            detail="Invalid alert level",
        )

    statement = select(PredictionHistory)

    if alert_level is not None:
        statement = statement.where(PredictionHistory.alert_level == alert_level)

    statement = (
        statement.order_by(PredictionHistory.id.desc()).offset(offset).limit(limit)
    )

    records = db.scalars(statement).all()

    return [
        PredictionHistoryResponse(
            prediction_id=record.id,
            machine_type=record.machine_type,
            air_temperature_k=record.air_temperature_k,
            process_temperature_k=record.process_temperature_k,
            rotational_speed_rpm=record.rotational_speed_rpm,
            torque_nm=record.torque_nm,
            tool_wear_min=record.tool_wear_min,
            failure_score=record.failure_score,
            predicted_failure=record.predicted_failure,
            alert_level=record.alert_level,
            model_version=record.model_version,
            created_at=record.created_at,
        )
        for record in records
    ]


@app.get(
    "/api/v1/dashboard/summary",
    response_model=DashboardSummaryResponse,
)
def dashboard_summary(db: DBSession):
    """Return aggregate prediction and alert statistics."""

    total_predictions = db.scalar(select(func.count(PredictionHistory.id))) or 0

    average_score = db.scalar(select(func.avg(PredictionHistory.failure_score)))

    alert_counts = db.execute(
        select(
            PredictionHistory.alert_level,
            func.count(PredictionHistory.id),
        ).group_by(PredictionHistory.alert_level)
    ).all()

    counts = {alert_level: count for alert_level, count in alert_counts}

    return DashboardSummaryResponse(
        total_predictions=total_predictions,
        high_priority_alerts=counts.get("high_priority", 0),
        review_alerts=counts.get("review", 0),
        no_alert_predictions=counts.get("no_alert", 0),
        average_failure_score=(
            float(average_score) if average_score is not None else 0.0
        ),
    )
