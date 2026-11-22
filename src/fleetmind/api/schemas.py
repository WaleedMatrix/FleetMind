"""Pydantic schemas for FleetMind API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AlertLevel = Literal[
    "no_alert",
    "review",
    "high_priority",
]


class MachineReading(BaseModel):
    """Machine sensor measurements."""

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
    )

    machine_type: Literal["L", "M", "H"]

    air_temperature_k: float = Field(gt=0)
    process_temperature_k: float = Field(gt=0)

    rotational_speed_rpm: float = Field(gt=0)
    torque_nm: float = Field(ge=0)
    tool_wear_min: float = Field(ge=0)


class PredictionResponse(BaseModel):
    """Result returned after saving a prediction."""

    prediction_id: int
    model_version: str
    failure_score: float = Field(ge=0, le=1)
    predicted_failure: bool
    alert_level: AlertLevel


class PredictionHistoryResponse(PredictionResponse):
    """Stored prediction with its original inputs."""

    model_config = ConfigDict(from_attributes=True)

    machine_type: Literal["L", "M", "H"]
    air_temperature_k: float
    process_temperature_k: float
    rotational_speed_rpm: float
    torque_nm: float
    tool_wear_min: float
    created_at: datetime


class DashboardSummaryResponse(BaseModel):
    """Aggregate statistics for the FleetMind dashboard."""

    total_predictions: int = Field(ge=0)
    high_priority_alerts: int = Field(ge=0)
    review_alerts: int = Field(ge=0)
    no_alert_predictions: int = Field(ge=0)
    average_failure_score: float = Field(ge=0, le=1)
