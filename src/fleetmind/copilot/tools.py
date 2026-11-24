"""Allowlisted read tools backed by FleetMind's existing services."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import HTTPException
from pydantic import Field, StringConstraints, TypeAdapter

from fleetmind.api.assets import (
    asset_summary,
    get_asset_or_404,
    list_asset_predictions,
    list_assets,
)
from fleetmind.api.model_intelligence import (
    ExplanationResponse,
    ModelIntelligenceResponse,
    explain_record,
)
from fleetmind.api.schemas import (
    AlertLevel,
    AssetId,
    AssetMonitoringResponse,
    AssetResponse,
    MachineType,
    PredictionHistoryResponse,
    ReadingSource,
)
from fleetmind.copilot.relevance import collect_knowledge
from fleetmind.copilot.schemas import PredictionId, StrictInput
from fleetmind.db.history import prediction_history
from fleetmind.db.models import PredictionHistory
from fleetmind.explainability import ModelExplainer
from fleetmind.knowledge.embeddings import get_embedder
from fleetmind.knowledge.schemas import SearchFilters, SearchHit


class AssetInput(StrictInput):
    asset_id: AssetId | None = None


class AssetSearch(StrictInput):
    query: Annotated[str, StringConstraints(min_length=2, max_length=120)]
    machine_type: MachineType | None = None
    limit: int = Field(default=5, ge=1, le=5)
    offset: int = Field(default=0, ge=0, le=1000)


class HistoryInput(AssetInput):
    limit: int = Field(default=5, ge=1, le=10)
    offset: int = Field(default=0, ge=0, le=1000)
    alert_level: AlertLevel | None = None
    source: ReadingSource | None = None


class PredictionInput(StrictInput):
    prediction_id: PredictionId


class KnowledgeInput(StrictInput):
    queries: list[Annotated[str, StringConstraints(min_length=1, max_length=512)]] = (
        Field(default_factory=list, max_length=2)
    )
    top_k: int = Field(default=5, ge=1, le=8)
    filters: SearchFilters = Field(default_factory=SearchFilters)


class KnowledgeResult(StrictInput):
    hits: list[SearchHit]
    keyword_fallback: bool


class EmptyInput(StrictInput):
    pass


@dataclass(frozen=True)
class ToolContext:
    question: str
    asset_id: str | None
    model_version: str
    explainer: ModelExplainer | None
    intelligence: ModelIntelligenceResponse | None
    prediction_id: int | None = None


class ToolFailure(RuntimeError):
    pass


def scoped_asset(args, context, *, required=True):
    if context.asset_id and args.asset_id and args.asset_id != context.asset_id:
        raise ToolFailure("asset_outside_selected_context")
    asset_id = args.asset_id or context.asset_id
    if required and not asset_id:
        raise ToolFailure("asset_id_required")
    return asset_id


def asset(db, args, context):
    return get_asset_or_404(db, scoped_asset(args, context))


def assets(db, args, context):
    rows = list_assets(
        db,
        limit=args.limit,
        offset=args.offset,
        q=args.query,
        machine_type=args.machine_type,
    )
    return [
        row
        for row in rows
        if context.asset_id is None or row.asset_id == context.asset_id
    ]


def history(db, args, context):
    return list_asset_predictions(
        scoped_asset(args, context),
        db,
        limit=args.limit,
        offset=args.offset,
        alert_level=args.alert_level,
        source=args.source,
    )


def summary(db, args, context):
    return asset_summary(scoped_asset(args, context), db)


def prediction(db, args, context):
    record = db.get(PredictionHistory, args.prediction_id)
    if (
        record is None
        or (context.asset_id and record.asset_id != context.asset_id)
        or (context.prediction_id and record.id != context.prediction_id)
    ):
        raise ToolFailure("prediction_not_found_in_scope")
    return record


def explanation(db, args, context):
    return explain_record(
        prediction(db, args, context), context.model_version, context.explainer
    )


def alerts(db, args, context):
    asset_id = scoped_asset(args, context, required=False)
    if asset_id:
        return list_asset_predictions(
            asset_id,
            db,
            limit=args.limit,
            offset=args.offset,
            alert_level=args.alert_level,
            source=args.source,
            alerts_only=True,
        )
    return prediction_history(
        db,
        limit=args.limit,
        offset=args.offset,
        alert_level=args.alert_level,
        source=args.source,
        alerts_only=True,
    )


def knowledge(db, args, context):
    hits, fallback = collect_knowledge(
        db,
        context.question,
        args.queries,
        get_embedder(),
        top_k=args.top_k,
        filters=args.filters,
    )
    return KnowledgeResult(hits=hits, keyword_fallback=fallback)


def model_info(db, args, context):
    if context.intelligence is None:
        raise ToolFailure("model_information_unavailable")
    return context.intelligence


@dataclass(frozen=True)
class Tool:
    description: str
    input: type[StrictInput]
    output: TypeAdapter
    handler: Callable

    def invoke(self, db, args, context):
        try:
            result = self.handler(db, args, context)
        except HTTPException as exc:
            status = {404: "record_not_found", 409: "model_version_unavailable"}.get(
                exc.status_code,
                "tool_unavailable",
            )
            raise ToolFailure(status) from None
        return self.output.validate_python(result, from_attributes=True)


REGISTRY = {
    "get_asset": Tool(
        "Read an exact registered asset ID.",
        AssetInput,
        TypeAdapter(AssetResponse),
        asset,
    ),
    "search_assets": Tool(
        "Resolve asset names or locations to registered IDs.",
        AssetSearch,
        TypeAdapter(list[AssetResponse]),
        assets,
    ),
    "get_asset_history": Tool(
        "Read paginated stored predictions for one asset.",
        HistoryInput,
        TypeAdapter(list[PredictionHistoryResponse]),
        history,
    ),
    "get_asset_summary": Tool(
        "Read aggregate counts and score for one asset.",
        AssetInput,
        TypeAdapter(AssetMonitoringResponse),
        summary,
    ),
    "get_prediction": Tool(
        "Read original saved inputs and outputs for one prediction ID.",
        PredictionInput,
        TypeAdapter(PredictionHistoryResponse),
        prediction,
    ),
    "explain_prediction": Tool(
        "Use the matching frozen model to explain a saved prediction's raw margin.",
        PredictionInput,
        TypeAdapter(ExplanationResponse),
        explanation,
    ),
    "list_recent_alerts": Tool(
        "Read stored review and high priority alerts.",
        HistoryInput,
        TypeAdapter(list[PredictionHistoryResponse]),
        alerts,
    ),
    "search_knowledge": Tool(
        "Find source passages. Propose distinct queries for separate aspects.",
        KnowledgeInput,
        TypeAdapter(KnowledgeResult),
        knowledge,
    ),
    "get_model_information": Tool(
        "Read frozen model metadata and verified evaluation.",
        EmptyInput,
        TypeAdapter(ModelIntelligenceResponse),
        model_info,
    ),
}


def tool_definitions():
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": tool.description,
                "parameters": tool.input.model_json_schema(),
            },
        }
        for name, tool in REGISTRY.items()
    ]
