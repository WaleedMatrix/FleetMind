"""Asset registry and prediction monitoring routes."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fleetmind.api.dependencies import DBSession
from fleetmind.api.schemas import (
    AlertLevel,
    AssetCreate,
    AssetId,
    AssetMonitoringResponse,
    AssetResponse,
    AssetUpdate,
    MachineType,
    PredictionHistoryResponse,
    ReadingSource,
)
from fleetmind.db.history import prediction_history
from fleetmind.db.models import Asset, PredictionHistory

router = APIRouter(prefix="/api/v1/assets", tags=["assets"])
PageLimit = Annotated[int, Query(ge=1, le=100)]
PageOffset = Annotated[int, Query(ge=0)]


def get_asset_or_404(db: Session, asset_id: str) -> Asset:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


@router.post("", response_model=AssetResponse, status_code=201)
def register_asset(payload: AssetCreate, db: DBSession):
    asset = Asset(**payload.model_dump())
    db.add(asset)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if db.get(Asset, payload.asset_id) is not None:
            raise HTTPException(
                status_code=409, detail="Asset ID already exists"
            ) from exc
        raise
    db.refresh(asset)
    return asset


@router.get("", response_model=list[AssetResponse])
def list_assets(
    db: DBSession,
    limit: PageLimit = 20,
    offset: PageOffset = 0,
    q: Annotated[str | None, Query(max_length=120)] = None,
    machine_type: MachineType | None = None,
):
    query = select(Asset)
    if q and (search := q.strip()):
        query = query.where(
            or_(
                Asset.asset_id.icontains(search, autoescape=True),
                Asset.display_name.icontains(search, autoescape=True),
                Asset.location.icontains(search, autoescape=True),
            )
        )
    if machine_type is not None:
        query = query.where(Asset.machine_type == machine_type)
    return list(db.scalars(query.order_by(Asset.asset_id).offset(offset).limit(limit)))


@router.get("/{asset_id}", response_model=AssetResponse)
def inspect_asset(asset_id: AssetId, db: DBSession):
    return get_asset_or_404(db, asset_id)


@router.patch("/{asset_id}", response_model=AssetResponse)
def update_asset(asset_id: AssetId, payload: AssetUpdate, db: DBSession):
    asset = get_asset_or_404(db, asset_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(asset, field, value)
    db.commit()
    db.refresh(asset)
    return asset


@router.get("/{asset_id}/predictions", response_model=list[PredictionHistoryResponse])
def list_asset_predictions(
    asset_id: AssetId,
    db: DBSession,
    limit: PageLimit = 20,
    offset: PageOffset = 0,
    alert_level: AlertLevel | None = None,
    source: ReadingSource | None = None,
    alerts_only: bool = False,
):
    get_asset_or_404(db, asset_id)
    return prediction_history(
        db,
        limit=limit,
        offset=offset,
        asset_id=asset_id,
        alert_level=alert_level,
        source=source,
        alerts_only=alerts_only,
    )


@router.get("/{asset_id}/summary", response_model=AssetMonitoringResponse)
def asset_summary(asset_id: AssetId, db: DBSession):
    get_asset_or_404(db, asset_id)
    record = PredictionHistory
    statement = select(
        func.count().label("total_predictions"),
        func.count()
        .filter(record.alert_level == "high_priority")
        .label("high_priority_alerts"),
        func.count().filter(record.alert_level == "review").label("review_alerts"),
        func.count()
        .filter(record.alert_level == "no_alert")
        .label("no_alert_predictions"),
        func.avg(record.failure_score).label("average_failure_score"),
        func.max(record.created_at).label("last_prediction_at"),
    ).where(record.asset_id == asset_id)
    return db.execute(statement).mappings().one()
