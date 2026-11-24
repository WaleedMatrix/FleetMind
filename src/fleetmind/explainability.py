"""Tree SHAP for the frozen FleetMind classifier and its fitted preprocessing."""

from dataclasses import dataclass
from threading import Lock

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from scipy.special import expit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from fleetmind.data.split import FEATURES
from fleetmind.features.engineering import THERMAL_GAP

METHOD = "TreeExplainer (tree_path_dependent)"
OUTPUT_UNIT = "raw_margin_log_odds"
FEATURE_LABELS = {
    "Type": ("Machine type", None),
    "Air temperature [K]": ("Air temperature", "K"),
    "Process temperature [K]": ("Process temperature", "K"),
    "Rotational speed [rpm]": ("Rotational speed", "RPM"),
    "Torque [Nm]": ("Torque", "N·m"),
    "Tool wear [min]": ("Tool wear", "min"),
    THERMAL_GAP: ("Thermal gap", "K"),
}


class ExplanationUnavailable(ValueError):
    """The loaded model or prediction cannot be explained safely."""


@dataclass(frozen=True)
class FeatureGroup:
    name: str
    indices: tuple[int, ...]
    transformed_features: tuple[str, ...]

    @property
    def label(self) -> str:
        return FEATURE_LABELS[self.name][0]

    @property
    def unit(self) -> str | None:
        return FEATURE_LABELS[self.name][1]


@dataclass(frozen=True)
class ExplainedBatch:
    transformed: NDArray
    contributions: NDArray
    grouped: NDArray
    baseline: NDArray
    raw_output: NDArray
    scores: NDArray


class ModelExplainer:
    def __init__(self, pipeline: Pipeline, model_version: str):
        from shap import TreeExplainer

        self.model_version = model_version
        self.preprocessing = pipeline[:-1]
        self.classifier = pipeline.named_steps["classifier"]
        preprocessor = pipeline.named_steps["preprocessor"]
        if (
            list(pipeline.feature_names_in_) != FEATURES
            or self.classifier.get_xgb_params()["objective"] != "binary:logistic"
            or list(self.classifier.classes_) != [0, 1]
        ):
            raise ExplanationUnavailable("Unsupported classifier inputs or objective")

        self.transformed_features = tuple(preprocessor.get_feature_names_out())
        numeric = preprocessor.output_indices_["numeric"]
        categorical = preprocessor.output_indices_["categorical"]
        encoder = preprocessor.named_transformers_["categorical"]
        if (
            not isinstance(encoder, OneHotEncoder)
            or list(encoder.feature_names_in_) != ["Type"]
            or self.classifier.n_features_in_ != len(self.transformed_features)
        ):
            raise ExplanationUnavailable("Unsupported fitted feature layout")

        groups = {
            self.transformed_features[index].removeprefix("numeric__"): (index,)
            for index in range(numeric.start, numeric.stop)
        }
        groups["Type"] = tuple(range(categorical.start, categorical.stop))
        names = [*FEATURES, *([THERMAL_GAP] if THERMAL_GAP in groups else [])]
        if set(names) != groups.keys() or sorted(
            index for indices in groups.values() for index in indices
        ) != list(range(len(self.transformed_features))):
            raise ExplanationUnavailable(
                "Fitted feature names or ordering are incompatible"
            )

        self.groups = tuple(
            FeatureGroup(
                name,
                groups[name],
                tuple(self.transformed_features[index] for index in groups[name]),
            )
            for name in names
        )
        self.explainer = TreeExplainer(
            self.classifier,
            feature_perturbation="tree_path_dependent",
            model_output="raw",
        )
        self.lock = Lock()

    def compute(self, frame: pd.DataFrame) -> ExplainedBatch:
        """Compute exact transformed-feature SHAP values, then sum category groups."""
        if list(frame.columns) != FEATURES or frame.empty:
            raise ExplanationUnavailable(
                "Expected the original ordered inference inputs"
            )
        transformed = self.preprocessing.transform(frame)
        # TreeExplainer's XGBoost path can set its expected value during evaluation.
        with self.lock:
            explanation = self.explainer(transformed, check_additivity=False)
        contributions = np.asarray(explanation.values, dtype=np.float64)
        baseline = np.asarray(explanation.base_values, dtype=np.float64)
        raw = np.asarray(self.classifier.predict(transformed, output_margin=True))
        scores = self.classifier.predict_proba(transformed)[:, 1]
        if (
            contributions.shape != transformed.shape
            or baseline.shape != raw.shape
            or not np.isfinite(contributions).all()
            or not np.allclose(
                baseline + contributions.sum(axis=1), raw, rtol=1e-5, atol=2e-5
            )
            or not np.allclose(expit(raw), scores, rtol=1e-6, atol=1e-7)
        ):
            raise ExplanationUnavailable("SHAP values failed raw margin verification")
        grouped = np.column_stack(
            [contributions[:, group.indices].sum(axis=1) for group in self.groups]
        )
        return ExplainedBatch(
            transformed, contributions, grouped, baseline, raw, scores
        )
