"""Database aggregation queries for FleetMind dashboards."""

from datetime import UTC

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from fleetmind.db.models import PredictionHistory


def get_prediction_trends(
    db: Session,
    interval: str = "hour",
) -> list[dict]:
    """Aggregate stored predictions into UTC time buckets."""

    if interval not in {"hour", "day"}:
        raise ValueError("interval must be 'hour' or 'day'")

    bucket = func.date_trunc(
        interval,
        PredictionHistory.created_at,
    )

    statement = (
        select(
            bucket.label("timestamp"),
            func.count(PredictionHistory.id).label("total_predictions"),
            func.sum(
                case(
                    (
                        PredictionHistory.alert_level == "high_priority",
                        1,
                    ),
                    else_=0,
                )
            ).label("high_priority_alerts"),
            func.sum(
                case(
                    (
                        PredictionHistory.alert_level == "review",
                        1,
                    ),
                    else_=0,
                )
            ).label("review_alerts"),
            func.sum(
                case(
                    (
                        PredictionHistory.alert_level == "no_alert",
                        1,
                    ),
                    else_=0,
                )
            ).label("no_alert_predictions"),
            func.avg(PredictionHistory.failure_score).label("average_failure_score"),
        )
        .group_by(bucket)
        .order_by(bucket)
    )

    rows = db.execute(statement).all()

    points = []

    for row in rows:
        timestamp = row.timestamp

        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)

        points.append(
            {
                "timestamp": timestamp,
                "total_predictions": int(row.total_predictions),
                "high_priority_alerts": int(row.high_priority_alerts),
                "review_alerts": int(row.review_alerts),
                "no_alert_predictions": int(row.no_alert_predictions),
                "average_failure_score": float(row.average_failure_score),
            }
        )

    return points
