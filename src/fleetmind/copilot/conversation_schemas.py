"""Typed conversation and stream contracts."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from fleetmind.api.schemas import AssetId
from fleetmind.copilot.schemas import ChatResponse, PredictionId, Question, Status

Title = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=120, pattern=r"^[^\x00]*$"
    ),
]
MessageState = Literal["pending", "completed", "cancelled", "failed"]
EventType = Literal[
    "started",
    "tool_started",
    "tool_completed",
    "evidence",
    "clarification",
    "final",
    "completed",
    "session_expired",
    "error",
    "cancelled",
]


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Title = "New conversation"
    asset_id: AssetId | None = None
    prediction_id: PredictionId | None = None


class ConversationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Title | None = None
    archived: Annotated[bool, Field(strict=True)] | None = None
    asset_id: AssetId | None = None
    prediction_id: PredictionId | None = None

    @model_validator(mode="after")
    def required_values(self):
        for field in ("title", "archived"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null.")
        return self


class ConversationInfo(ConversationCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    archived: bool
    created_at: datetime
    updated_at: datetime


class ConversationPage(BaseModel):
    items: list[ConversationInfo]
    next_offset: int | None = None


class MessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    question: Question

    @field_validator("question")
    @classmethod
    def no_nul(cls, value: str) -> str:
        if "\0" in value:
            raise ValueError("Question cannot contain NUL characters.")
        return value


class MessageInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    request_id: UUID
    role: Literal["user", "assistant"]
    state: MessageState
    content: str
    asset_id: AssetId | None = None
    prediction_id: PredictionId | None = None
    response_status: Status | None = None
    response: ChatResponse | None = None
    provider: str | None = None
    model: str | None = None
    created_at: datetime


class MessagePage(BaseModel):
    items: list[MessageInfo]
    next_before_id: int | None = None


class RequestState(BaseModel):
    state: MessageState


class StreamEvent(BaseModel):
    type: EventType
    request_id: UUID
    tool: str | None = None
    outcome: Literal["ok", "error"] | None = None
    count: int | None = None
    user: MessageInfo | None = None
    message: MessageInfo | None = None
    detail: str | None = None
