from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from fleetmind.api.schemas import AssetId

Question = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1200)
]
Status = Literal[
    "answered", "clarification_required", "insufficient_evidence", "unavailable"
]
PredictionId = Annotated[int, Field(strict=True, gt=0, le=2_147_483_647)]


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class ChatContext(StrictInput):
    role: Literal["user", "assistant"]
    content: Annotated[str, StringConstraints(min_length=1, max_length=600)]


class ChatRequest(StrictInput):
    question: Question
    asset_id: AssetId | None = None
    context: list[ChatContext] = Field(default_factory=list, max_length=4)


class ToolCall(StrictInput):
    id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,120}$")]
    name: Annotated[str, StringConstraints(pattern=r"^[a-z_]{1,60}$")]
    arguments: Annotated[str, StringConstraints(max_length=4000)]


class Tokens(StrictInput):
    input: int = Field(ge=0)
    output: int = Field(ge=0)


class Citation(BaseModel):
    id: str
    kind: Literal["asset", "prediction", "explanation", "model", "knowledge"]
    title: str
    asset_id: AssetId | None = None
    prediction_id: PredictionId | None = None
    document_id: str | None = None
    chunk_id: str | None = None
    source_ref: str | None = None
    section: str | None = None


class Fact(BaseModel):
    id: str
    text: str
    citation: Citation


class Diagnostics(BaseModel):
    elapsed_ms: float = 0
    tool_rounds: int = 0
    tool_count: int = 0
    provider_calls: int = 0
    valid_tool_arguments: int = 0
    tool_names: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    tokens: Tokens | None = None


class ChatResponse(BaseModel):
    answer: str
    status: Status
    citations: list[Citation] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    asset_ids: list[AssetId] = Field(default_factory=list)
    prediction_ids: list[PredictionId] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    diagnostics: Diagnostics


class FinalSelection(StrictInput):
    status: Literal["answered", "clarification_required", "insufficient_evidence"]
    fact_ids: list[Annotated[str, StringConstraints(pattern=r"^f[1-9][0-9]{0,2}$")]] = (
        Field(max_length=8)
    )
