"""Versioned telemetry and redacted dead-letter contracts."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from fleetmind.api.schemas import AssetId, MachineReading

TelemetrySource = Literal["simulated", "telemetry"]
RejectedCategory = Literal[
    "invalid_payload",
    "unsupported_version",
    "partition_key_mismatch",
    "missing_asset",
    "machine_type_mismatch",
    "event_id_conflict",
]
PositiveMeasurement = Annotated[float, Field(gt=0, le=1_000_000_000)]
NonnegativeMeasurement = Annotated[float, Field(ge=0, le=1_000_000_000)]
MAX_EVENT_BYTES = 16_384


class TelemetryEvent(MachineReading):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)

    event_id: UUID
    schema_version: Literal[1]
    asset_id: AssetId
    observed_at: AwareDatetime
    source: TelemetrySource
    air_temperature_k: PositiveMeasurement
    process_temperature_k: PositiveMeasurement
    rotational_speed_rpm: PositiveMeasurement
    torque_nm: NonnegativeMeasurement
    tool_wear_min: NonnegativeMeasurement

    @field_validator("observed_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("observed_at must be in UTC")
        return value.astimezone(UTC)

    @field_validator("schema_version", mode="before")
    @classmethod
    def require_integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("schema_version must be an integer")
        return value


class DeadLetter(BaseModel):
    schema_version: Literal[1] = 1
    category: RejectedCategory
    rejected_at: datetime
    original_topic: str
    original_partition: int
    original_offset: int
    event_id: UUID | None = None


class TelemetryStatus(BaseModel):
    state: Literal["ready", "migration_required", "unavailable"]
    persisted_assessments: int | None = None
    last_ingested_at: datetime | None = None
    last_assessed_at: datetime | None = None
