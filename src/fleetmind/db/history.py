from sqlalchemy import select
from sqlalchemy.orm import Session

from fleetmind.db.models import PredictionHistory


def prediction_history(
    db: Session,
    *,
    limit: int,
    offset: int,
    asset_id: str | None = None,
    alert_level: str | None = None,
    source: str | None = None,
    alerts_only: bool = False,
) -> list[PredictionHistory]:
    record = PredictionHistory
    query = select(record)
    if asset_id is not None:
        query = query.where(record.asset_id == asset_id)
    if alert_level is not None:
        query = query.where(record.alert_level == alert_level)
    if source is not None:
        query = query.where(record.source == source)
    if alerts_only:
        query = query.where(record.alert_level.in_(("high_priority", "review")))
    return list(
        db.scalars(query.order_by(record.id.desc()).offset(offset).limit(limit))
    )
