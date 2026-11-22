"""SQLAlchemy models for FleetMind prediction storage."""

from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    Float,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from fleetmind.db.database import Base


class PredictionHistory(Base):
    """Store a machine reading and its model prediction."""

    __tablename__ = "prediction_history"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    machine_type: Mapped[str] = mapped_column(
        String(1),
        nullable=False,
    )

    air_temperature_k: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    process_temperature_k: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    rotational_speed_rpm: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    torque_nm: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    tool_wear_min: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    failure_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    predicted_failure: Mapped[bool] = mapped_column(
        nullable=False,
    )

    alert_level: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    model_version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
