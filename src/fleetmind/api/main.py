"""FleetMind API with PostgreSQL prediction persistence."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import joblib
from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import func, select

from fleetmind.api.assets import get_asset_or_404
from fleetmind.api.assets import router as assets_router
from fleetmind.api.copilot import router as copilot_router
from fleetmind.api.dependencies import DBSession
from fleetmind.api.inference import (
    classify_alert,
    to_model_frame,
)
from fleetmind.api.knowledge import router as knowledge_router
from fleetmind.api.model_intelligence import load_model_intelligence
from fleetmind.api.model_intelligence import router as model_router
from fleetmind.api.schemas import (
    AssetId,
    DashboardSummaryResponse,
    DashboardTrendsResponse,
    PredictionHistoryResponse,
    PredictionRequest,
    PredictionResponse,
    ReadingSource,
)
from fleetmind.config import MODEL_VERSION, PRIMARY_THRESHOLD
from fleetmind.db.analytics import get_prediction_trends
from fleetmind.db.history import prediction_history
from fleetmind.db.models import PredictionHistory
from fleetmind.explainability import ModelExplainer

PROJECT_ROOT = Path(__file__).resolve().parents[3]

MODEL_PATH = PROJECT_ROOT / "artifacts" / "models" / f"{MODEL_VERSION}.joblib"
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load the frozen model once at application startup."""

    if not MODEL_PATH.is_file():
        raise FileNotFoundError(f"Model artifact not found: {MODEL_PATH}")

    # Load only trusted model artifacts.
    app.state.model = joblib.load(MODEL_PATH)
    app.state.model_version = MODEL_VERSION
    app.state.explainer = None
    try:
        app.state.explainer = ModelExplainer(app.state.model, MODEL_VERSION)
    except Exception:
        logger.exception("Model explainability could not be initialized")
    app.state.model_intelligence = load_model_intelligence(
        PROJECT_ROOT, MODEL_PATH, MODEL_VERSION, app.state.explainer
    )

    print(f"Loaded FleetMind model: {MODEL_VERSION}")

    try:
        yield
    finally:
        del app.state.explainer
        del app.state.model_intelligence
        del app.state.model_version
        del app.state.model


app = FastAPI(
    title="FleetMind API",
    description="Machine failure classification and history API.",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(assets_router)
app.include_router(model_router)
app.include_router(knowledge_router)
app.include_router(copilot_router)


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
    reading: PredictionRequest,
    request: Request,
    db: DBSession,
):
    """Generate and persist a machine failure prediction."""

    if reading.asset_id is not None:
        asset = get_asset_or_404(db, reading.asset_id)
        if asset.machine_type != reading.machine_type:
            raise HTTPException(
                status_code=422,
                detail="Reading machine type must match the registered asset type",
            )

    model = request.app.state.model
    features = to_model_frame(reading)

    score = float(model.predict_proba(features)[0, 1])

    predicted_failure = score >= PRIMARY_THRESHOLD
    alert_level = classify_alert(score)

    record = PredictionHistory(
        asset_id=reading.asset_id,
        source=reading.source,
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

    return record


@app.get(
    "/api/v1/predictions",
    response_model=list[PredictionHistoryResponse],
)
def list_predictions(
    db: DBSession,
    limit: int = 20,
    offset: int = 0,
    alert_level: str | None = None,
    asset_id: AssetId | None = None,
    source: ReadingSource | None = None,
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

    return prediction_history(
        db,
        limit=limit,
        offset=offset,
        asset_id=asset_id,
        alert_level=alert_level,
        source=source,
    )


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


@app.get(
    "/api/v1/dashboard/trends",
    response_model=DashboardTrendsResponse,
)
def dashboard_trends(
    db: DBSession,
    interval: str = "hour",
):
    """Return hourly or daily prediction trends."""

    if interval not in {"hour", "day"}:
        raise HTTPException(
            status_code=422,
            detail="interval must be 'hour' or 'day'",
        )

    points = get_prediction_trends(
        db=db,
        interval=interval,
    )

    return DashboardTrendsResponse(
        interval=interval,
        points=points,
    )
