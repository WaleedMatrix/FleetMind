"""Pydantic schemas for FleetMind API."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

AlertLevel = Literal[
    "no_alert",
    "review",
    "high_priority",
]
MachineType = Literal["L", "M", "H"]
ReadingSource = Literal["unknown", "manual", "simulated", "telemetry"]
AssetId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    ),
]
AssetName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]
Location = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]


class AssetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: AssetId
    display_name: AssetName
    machine_type: MachineType
    location: Location | None = None
    description: Description | None = None


class AssetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: AssetName | None = None
    location: Location | None = None
    description: Description | None = None

    @field_validator("display_name")
    @classmethod
    def reject_null_name(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("Display name cannot be null")
        return value


class AssetResponse(AssetCreate):
    model_config = ConfigDict(from_attributes=True)

    created_at: datetime


class MachineReading(BaseModel):
    """Machine sensor measurements."""

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
    )

    machine_type: MachineType

    air_temperature_k: float = Field(gt=0)
    process_temperature_k: float = Field(gt=0)

    rotational_speed_rpm: float = Field(gt=0)
    torque_nm: float = Field(ge=0)
    tool_wear_min: float = Field(ge=0)


class PredictionRequest(MachineReading):
    asset_id: AssetId | None = None
    source: ReadingSource = "unknown"


class PredictionResponse(BaseModel):
    """Result returned after saving a prediction."""

    model_config = ConfigDict(from_attributes=True)

    prediction_id: int = Field(validation_alias=AliasChoices("prediction_id", "id"))
    model_version: str
    failure_score: float = Field(ge=0, le=1)
    predicted_failure: bool
    alert_level: AlertLevel
    asset_id: AssetId | None = None
    source: ReadingSource = "unknown"


class PredictionHistoryResponse(PredictionResponse):
    """Stored prediction with its original inputs."""

    model_config = ConfigDict(from_attributes=True)

    machine_type: MachineType
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


class AssetMonitoringResponse(BaseModel):
    total_predictions: int = Field(ge=0)
    high_priority_alerts: int = Field(ge=0)
    review_alerts: int = Field(ge=0)
    no_alert_predictions: int = Field(ge=0)
    average_failure_score: float | None = Field(ge=0, le=1)
    last_prediction_at: datetime | None


class TrendPoint(BaseModel):
    """Aggregated prediction metrics for a time bucket."""

    timestamp: datetime
    total_predictions: int = Field(ge=0)
    high_priority_alerts: int = Field(ge=0)
    review_alerts: int = Field(ge=0)
    no_alert_predictions: int = Field(ge=0)
    average_failure_score: float = Field(ge=0, le=1)


class DashboardTrendsResponse(BaseModel):
    """Time-series data for the monitoring dashboard."""

    interval: Literal["hour", "day"]
    points: list[TrendPoint]
