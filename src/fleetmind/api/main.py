"""FleetMind API with PostgreSQL prediction persistence."""

import logging
import os
from contextlib import asynccontextmanager
from threading import Thread
from typing import Annotated

from fastapi import FastAPI, HTTPException, Request
from fastapi import Path as PathParam
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from fleetmind.api.assets import router as assets_router
from fleetmind.api.copilot import router as copilot_router
from fleetmind.api.copilot_conversations import router as conversation_router
from fleetmind.api.dependencies import DBSession
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
from fleetmind.api.security import router as security_router
from fleetmind.api.telemetry import router as telemetry_router
from fleetmind.config import MODEL_VERSION
from fleetmind.db.analytics import get_prediction_trends
from fleetmind.db.history import prediction_history
from fleetmind.db.models import PredictionHistory
from fleetmind.explainability import ModelExplainer
from fleetmind.knowledge.embeddings import get_embedder
from fleetmind.security.protect import SecurityMiddleware
from fleetmind.security.store import dummy_hash
from fleetmind.services.predictions import (
    MODEL_PATH,
    PROJECT_ROOT,
    AssetValidationError,
    assess,
    load_frozen_model,
    validate_asset,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load the frozen model once at application startup."""

    app.state.model = load_frozen_model()
    dummy_hash()
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
    if os.getenv("FLEETMIND_COPILOT_PREWARM", "0") == "1":
        Thread(
            target=get_embedder().prewarm_offline, daemon=True, name="embedding-prewarm"
        ).start()

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
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    redirect_slashes=False,
)
app.add_middleware(SecurityMiddleware)
app.include_router(security_router)
app.include_router(assets_router)
app.include_router(model_router)
app.include_router(knowledge_router)
app.include_router(copilot_router)
app.include_router(conversation_router)
app.include_router(telemetry_router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/v1/system/status")
def system_status(request: Request):
    return {
        "status": "ok",
        "model_loaded": hasattr(request.app.state, "model"),
        "model_version": MODEL_VERSION,
    }


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    protected_input = request.url.path.startswith(("/api/v1/auth/", "/api/v1/admin/"))
    errors = [
        {
            "loc": item["loc"],
            "type": item["type"],
            "msg": "Invalid field." if protected_input else item["msg"],
        }
        for item in exc.errors()
    ]
    return JSONResponse({"detail": errors}, status_code=422)


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

    if request.state.principal.is_service and reading.source != "simulated":
        request.state.auth_store.record("service_source_denied")
        raise HTTPException(
            403, "Service credentials may submit simulated readings only."
        )

    try:
        validate_asset(db, reading.asset_id, reading)
    except AssetValidationError as exc:
        if exc.category == "missing_asset":
            raise HTTPException(status_code=404, detail="Asset not found") from exc
        raise HTTPException(
            status_code=422,
            detail="Reading machine type must match the registered asset type",
        ) from exc
    record = assess(
        db,
        request.app.state.model,
        reading,
        asset_id=reading.asset_id,
        source=reading.source,
    )

    try:
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
    "/api/v1/predictions/{prediction_id}", response_model=PredictionHistoryResponse
)
def prediction_detail(
    prediction_id: Annotated[int, PathParam(gt=0, le=2_147_483_647)], db: DBSession
):
    record = db.get(PredictionHistory, prediction_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Prediction not found.")
    return record


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
