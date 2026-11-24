"""Prediction explanations and provenance-checked model intelligence."""

import hashlib
import logging
from math import isclose
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi import Path as PathParam
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from fleetmind.api.dependencies import DBSession
from fleetmind.api.inference import to_model_frame
from fleetmind.api.schemas import MachineReading
from fleetmind.db.models import PredictionHistory
from fleetmind.explainability import METHOD, OUTPUT_UNIT, ModelExplainer
from fleetmind.features.engineering import THERMAL_GAP

router = APIRouter(prefix="/api/v1", tags=["model intelligence"])
logger = logging.getLogger(__name__)
UnitInterval = Annotated[float, Field(ge=0, le=1)]
PositiveInt = Annotated[int, Field(gt=0)]
Count = Annotated[int, Field(ge=0)]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class ExplanationFeature(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    name: str
    label: str
    value: str | float
    unit: str | None
    derived: bool
    transformed_features: list[str]
    contribution: float


class ExplanationResponse(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    prediction_id: int
    model_version: str
    method: Literal["TreeExplainer (tree_path_dependent)"] = METHOD
    output_unit: Literal["raw_margin_log_odds"] = OUTPUT_UNIT
    baseline: float
    raw_output: float
    failure_score: UnitInterval
    features: list[ExplanationFeature]


class ImportanceFeature(BaseModel):
    name: str
    label: str
    transformed_features: list[str]
    mean_absolute_shap: Annotated[float, Field(ge=0, allow_inf_nan=False)]


class GlobalImportance(BaseModel):
    model_version: str
    model_sha256: Digest
    dataset_sha256: Digest
    dataset_split: Literal["training"]
    split_seed: int
    holdout_fraction: UnitInterval
    sample_size: PositiveInt
    sample_seed: int
    method: Literal["TreeExplainer (tree_path_dependent)"]
    output_unit: Literal["raw_margin_log_odds"]
    shap_version: str
    features: list[ImportanceFeature] = Field(min_length=1)


class Thresholds(BaseModel):
    review: UnitInterval
    primary: UnitInterval
    high_priority: UnitInterval


class FrozenMetadata(BaseModel):
    model_name: str
    model_version: str
    algorithm: str
    input_features: list[str]
    training_observations: PositiveInt
    training_failures: Count
    scale_pos_weight: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    thresholds: Thresholds
    dataset_sha256: Digest
    evaluation_report: Literal["reports/final_test_metrics.json"]
    feature_engineering: dict[str, bool]
    dependencies: dict[str, str]


class ThresholdMetrics(BaseModel):
    threshold: UnitInterval
    accuracy: UnitInterval
    precision: UnitInterval
    recall: UnitInterval
    f1: UnitInterval
    true_positive: Count = Field(validation_alias=AliasChoices("TP", "true_positive"))
    false_positive: Count = Field(validation_alias=AliasChoices("FP", "false_positive"))
    false_negative: Count = Field(validation_alias=AliasChoices("FN", "false_negative"))
    true_negative: Count = Field(validation_alias=AliasChoices("TN", "true_negative"))


class HeldOutEvaluation(BaseModel):
    model_name: str
    model_version: str
    dataset: str
    use_thermal_gap: bool
    training_observations: PositiveInt
    training_failures: Count
    test_observations: PositiveInt
    test_failures: Count
    average_precision: UnitInterval
    threshold_configuration: Thresholds
    primary_threshold_results: ThresholdMetrics


class ModelIntelligenceResponse(BaseModel):
    metadata: FrozenMetadata
    global_importance: GlobalImportance | None
    evaluation: HeldOutEvaluation | None


def load_model_intelligence(
    root: Path,
    model_path: Path,
    model_version: str,
    explainer: ModelExplainer | None,
) -> ModelIntelligenceResponse | None:
    try:
        metadata = FrozenMetadata.model_validate_json(
            model_path.with_suffix(".metadata.json").read_text(encoding="utf-8")
        )
        if metadata.model_version != model_version:
            raise ValueError(
                "Model metadata version does not match the configured model"
            )
    except (OSError, ValueError) as exc:
        logger.warning("Model metadata unavailable: %s", exc)
        return None

    evaluation = None
    try:
        report = HeldOutEvaluation.model_validate_json(
            (root / metadata.evaluation_report).read_text(encoding="utf-8")
        )
        metrics = report.primary_threshold_results
        if (
            report.model_version != model_version
            or report.model_name != metadata.model_name
            or report.training_observations != metadata.training_observations
            or report.training_failures != metadata.training_failures
            or report.use_thermal_gap != metadata.feature_engineering.get("thermal_gap")
            or report.threshold_configuration != metadata.thresholds
            or metrics.threshold != metadata.thresholds.primary
            or metrics.true_positive + metrics.false_negative != report.test_failures
            or metrics.true_negative + metrics.false_positive
            != report.test_observations - report.test_failures
        ):
            raise ValueError("Held-out evaluation does not match the frozen metadata")
        evaluation = report
    except (OSError, ValueError) as exc:
        logger.warning("Held-out evaluation unavailable: %s", exc)

    importance = None
    try:
        report_path = root / "reports" / f"global_shap_{model_version}.json"
        global_report = GlobalImportance.model_validate_json(
            report_path.read_text(encoding="utf-8")
        )
        if (
            global_report.model_version != model_version
            or global_report.dataset_sha256 != metadata.dataset_sha256
            or global_report.model_sha256
            != hashlib.sha256(model_path.read_bytes()).hexdigest()
            or global_report.sample_size > metadata.training_observations
            or (
                explainer is not None
                and [
                    (entry.name, tuple(entry.transformed_features))
                    for entry in global_report.features
                ]
                != [
                    (group.name, group.transformed_features)
                    for group in explainer.groups
                ]
            )
        ):
            raise ValueError("Global SHAP report does not match the frozen model")
        importance = global_report
    except (OSError, ValueError) as exc:
        logger.warning("Global explanation unavailable: %s", exc)
    return ModelIntelligenceResponse(
        metadata=metadata, global_importance=importance, evaluation=evaluation
    )


@router.get("/model/intelligence", response_model=ModelIntelligenceResponse)
def model_intelligence(request: Request):
    intelligence = request.app.state.model_intelligence
    if intelligence is None:
        raise HTTPException(
            status_code=503, detail="Frozen model metadata is unavailable."
        )
    return intelligence


@router.get(
    "/predictions/{prediction_id}/explanation", response_model=ExplanationResponse
)
def explain_prediction(
    prediction_id: Annotated[int, PathParam(gt=0, le=2_147_483_647)],
    request: Request,
    db: DBSession,
):
    record = db.get(PredictionHistory, prediction_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Prediction not found.")
    return explain_record(
        record, request.app.state.model_version, request.app.state.explainer
    )


def explain_record(
    record: PredictionHistory,
    model_version: str,
    explainer: ModelExplainer | None,
) -> ExplanationResponse:
    if record.model_version != model_version:
        raise HTTPException(
            status_code=409,
            detail=f"Model {record.model_version} is unavailable for explanation.",
        )
    if explainer is None:
        raise HTTPException(
            status_code=503, detail="The model explainer is unavailable."
        )
    try:
        reading = MachineReading.model_validate(record, from_attributes=True)
        frame = to_model_frame(reading)
        explanation = explainer.compute(frame)
        if not isclose(
            float(explanation.scores[0]),
            record.failure_score,
            rel_tol=1e-6,
            abs_tol=1e-7,
        ):
            raise ValueError("The loaded model does not reproduce the saved score")
        features = []
        for index, group in enumerate(explainer.groups):
            derived = group.name == THERMAL_GAP
            value = (
                float(explanation.transformed[0, group.indices[0]])
                if derived
                else frame[group.name].iat[0]
            )
            features.append(
                ExplanationFeature(
                    name=group.name,
                    label=group.label,
                    value=value,
                    unit=group.unit,
                    derived=derived,
                    transformed_features=list(group.transformed_features),
                    contribution=float(explanation.grouped[0, index]),
                )
            )
        return ExplanationResponse(
            prediction_id=record.id,
            model_version=record.model_version,
            baseline=float(explanation.baseline[0]),
            raw_output=float(explanation.raw_output[0]),
            failure_score=record.failure_score,
            features=features,
        )
    except Exception as exc:
        logger.exception("Unable to explain prediction %d", record.id)
        raise HTTPException(
            status_code=503,
            detail="An explanation could not be verified for this saved prediction.",
        ) from exc
