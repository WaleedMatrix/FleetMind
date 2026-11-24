"""SQLAlchemy models for FleetMind prediction storage."""

from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from fleetmind.db.database import Base


class Asset(Base):
    """A registered machine with its own stable asset identifier."""

    __tablename__ = "assets"
    __table_args__ = (
        CheckConstraint(
            "machine_type IN ('L', 'M', 'H')", name="ck_assets_machine_type"
        ),
        Index("ix_assets_machine_type_asset_id", "machine_type", "asset_id"),
    )

    asset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120))
    machine_type: Mapped[str] = mapped_column(String(1))
    location: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP")
    )


class PredictionHistory(Base):
    """Store a machine reading and its model prediction."""

    __tablename__ = "prediction_history"
    __table_args__ = (
        CheckConstraint(
            "source IN ('unknown', 'manual', 'simulated', 'telemetry')",
            name="ck_prediction_history_source",
        ),
        Index("ix_prediction_history_asset_id_id", "asset_id", "id"),
        Index(
            "ix_prediction_history_asset_alert_id",
            "asset_id",
            "alert_level",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.asset_id", name="fk_prediction_history_asset_id")
    )
    source: Mapped[str] = mapped_column(String(12), server_default="unknown")

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
