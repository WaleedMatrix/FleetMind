"""Versioned training reference histograms and bounded operational comparisons."""

from datetime import UTC, datetime, timedelta
from hashlib import file_digest, sha256
from json import dumps
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from fleetmind.api.schemas import ReadingSource
from fleetmind.config import MODEL_VERSION
from fleetmind.db.models import PredictionHistory
from fleetmind.features.engineering import THERMAL_GAP
from fleetmind.services.predictions import MODEL_PATH, PROJECT_ROOT

MIN_OBSERVATIONS = 100
MAX_OBSERVATIONS = 5000
PSI_NOTICE = 0.10
PSI_HIGH = 0.25
JS_NOTICE = 0.05
JS_HIGH = 0.10
SENSOR_FIELDS = {
    "air_temperature_k": "Air temperature [K]",
    "process_temperature_k": "Process temperature [K]",
    "rotational_speed_rpm": "Rotational speed [rpm]",
    "torque_nm": "Torque [Nm]",
    "tool_wear_min": "Tool wear [min]",
    "thermal_gap_k": THERMAL_GAP,
    "failure_score": "Failure score",
}
CATEGORIES = {
    "machine_type": ("L", "M", "H"),
    "alert_level": ("no_alert", "review", "high_priority"),
}
DistributionKey = Literal[
    "air_temperature_k",
    "process_temperature_k",
    "rotational_speed_rpm",
    "torque_nm",
    "tool_wear_min",
    "thermal_gap_k",
    "failure_score",
    "machine_type",
    "alert_level",
]


class Histogram(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    key: DistributionKey
    edges: list[float] = Field(default_factory=list, max_length=9)
    categories: list[str] = Field(default_factory=list, max_length=3)
    counts: list[int] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def check_shape(self):
        if self.key in CATEGORIES:
            valid = (
                tuple(self.categories) == CATEGORIES[self.key]
                and not self.edges
                and len(self.counts) == len(self.categories)
            )
        else:
            valid = (
                not self.categories
                and self.edges == sorted(set(self.edges))
                and len(self.counts) == len(self.edges) + 1
            )
        if not valid or any(count < 0 for count in self.counts):
            raise ValueError("Invalid reference histogram.")
        return self


class Reference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    model_version: str
    model_sha256: str
    metadata_sha256: str
    dataset: Literal["UCI AI4I 2020"]
    dataset_sha256: str
    split: Literal["stratified_training"]
    split_seed: int
    holdout_fraction: float
    sample_size: int = Field(gt=0)
    histograms: list[Histogram]
    reference_sha256: str

    @model_validator(mode="after")
    def check_reference(self):
        expected = [*SENSOR_FIELDS, *CATEGORIES]
        if [item.key for item in self.histograms] != expected or any(
            sum(item.counts) != self.sample_size for item in self.histograms
        ):
            raise ValueError("Reference coverage or sample totals are inconsistent.")
        if (
            fingerprint(self.model_dump(mode="json", exclude={"reference_sha256"}))
            != self.reference_sha256
        ):
            raise ValueError("Reference fingerprint mismatch.")
        return self


class ReferenceInfo(BaseModel):
    schema_version: int
    dataset: str
    dataset_sha256: str
    split: str
    split_seed: int
    holdout_fraction: float
    sample_size: int
    reference_sha256: str


class Comparison(BaseModel):
    key: DistributionKey
    edges: list[float]
    categories: list[str]
    reference_counts: list[int]
    observed_counts: list[int]
    statistic: Literal["psi", "js_bits"]
    value: float | None
    indicator: Literal["within_threshold", "notice", "elevated"] | None


class ModelHealth(BaseModel):
    state: Literal["ready", "insufficient_data", "unavailable"]
    model_version: str
    integrity: Literal["verified", "unverified"]
    reference: ReferenceInfo | None = None
    source: ReadingSource
    since: datetime
    as_of: datetime
    time_basis: Literal["assessment_created_at"] = "assessment_created_at"
    observations: int = 0
    minimum_observations: int = MIN_OBSERVATIONS
    sample_limit: int = MAX_OBSERVATIONS
    truncated: bool = False
    comparisons: list[Comparison] = Field(default_factory=list)


def fingerprint(payload):
    return sha256(
        dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def hash_file(path: Path) -> str:
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def read_reference(
    path=PROJECT_ROOT / "reports" / f"model_reference_{MODEL_VERSION}.json",
    model_path=MODEL_PATH,
):
    reference = Reference.model_validate_json(path.read_bytes())
    if (
        reference.model_version != MODEL_VERSION
        or reference.model_sha256 != hash_file(model_path)
        or reference.metadata_sha256
        != hash_file(model_path.with_suffix(".metadata.json"))
    ):
        raise ValueError("Reference targets a different frozen model.")
    return reference


def bins(values, edges):
    return np.bincount(
        np.searchsorted(edges, values, side="right"),
        minlength=len(edges) + 1,
    ).tolist()


def quantile_edges(values):
    low, high = np.min(values), np.max(values)
    edges = np.unique(np.quantile(values, np.arange(1, 10) / 10))
    return [float(value) for value in edges if low < value < high]


def category_counts(values, categories):
    return [values.count(category) for category in categories]


def compare(reference, observed, *, categorical: bool):
    # Jeffreys pseudocount keeps logarithms finite, including empty bins.
    p = np.asarray(reference, dtype=float) + 0.5
    q = np.asarray(observed, dtype=float) + 0.5
    p /= p.sum()
    q /= q.sum()
    if categorical:
        midpoint = (p + q) / 2
        distance = float(
            (np.sum(p * np.log2(p / midpoint)) + np.sum(q * np.log2(q / midpoint))) / 2
        )
        return distance, JS_NOTICE, JS_HIGH
    distance = float(np.sum((q - p) * np.log(q / p)))
    return distance, PSI_NOTICE, PSI_HIGH


def values_for(rows, key):
    if key == "thermal_gap_k":
        return [row.process_temperature_k - row.air_temperature_k for row in rows]
    return [getattr(row, key) for row in rows]


def model_health(db, reference, source: ReadingSource, hours: int, *, now=None):
    now = now or datetime.now(UTC)
    since = now - timedelta(hours=hours)
    if reference is None:
        return ModelHealth(
            state="unavailable",
            integrity="unverified",
            model_version=MODEL_VERSION,
            source=source,
            since=since,
            as_of=now,
        )
    rows = list(
        db.scalars(
            select(PredictionHistory)
            .where(
                PredictionHistory.model_version == MODEL_VERSION,
                PredictionHistory.source == source,
                PredictionHistory.created_at >= since,
                PredictionHistory.created_at <= now,
            )
            .order_by(PredictionHistory.created_at.desc(), PredictionHistory.id.desc())
            .limit(MAX_OBSERVATIONS + 1)
        )
    )
    truncated = len(rows) > MAX_OBSERVATIONS
    rows = rows[:MAX_OBSERVATIONS]
    ready = len(rows) >= MIN_OBSERVATIONS
    comparisons = []
    for histogram in reference.histograms:
        values = values_for(rows, histogram.key)
        categorical = bool(histogram.categories)
        observed = (
            category_counts(values, histogram.categories)
            if categorical
            else bins(values, histogram.edges)
        )
        value = indicator = None
        if ready:
            value, notice, high = compare(
                histogram.counts, observed, categorical=categorical
            )
            indicator = (
                "elevated"
                if value >= high
                else "notice"
                if value >= notice
                else "within_threshold"
            )
        comparisons.append(
            Comparison(
                key=histogram.key,
                edges=histogram.edges,
                categories=histogram.categories,
                reference_counts=histogram.counts,
                observed_counts=observed,
                statistic="js_bits" if categorical else "psi",
                value=value,
                indicator=indicator,
            )
        )
    return ModelHealth(
        state="ready" if ready else "insufficient_data",
        integrity="verified",
        model_version=MODEL_VERSION,
        reference=ReferenceInfo.model_validate(reference.model_dump()),
        source=source,
        since=since,
        as_of=now,
        observations=len(rows),
        truncated=truncated,
        comparisons=comparisons,
    )
