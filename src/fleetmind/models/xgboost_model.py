from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder
from xgboost import XGBClassifier

from fleetmind.features.engineering import (
    THERMAL_GAP,
    add_thermal_gap,
)
from fleetmind.models.logistic import (
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
)


def build_xgboost_pipeline(
    scale_pos_weight: float = 1.0,
    use_thermal_gap: bool = False,
) -> Pipeline:
    """Build an XGBoost classification pipeline."""

    numeric_features = list(NUMERIC_FEATURES)

    if use_thermal_gap:
        numeric_features.append(THERMAL_GAP)

    preprocessor = ColumnTransformer(
        transformers=[
            (
                "numeric",
                "passthrough",
                numeric_features,
            ),
            (
                "categorical",
                OneHotEncoder(
                    handle_unknown="ignore",
                    sparse_output=False,
                ),
                CATEGORICAL_FEATURES,
            ),
        ],
        sparse_threshold=0,
    )

    classifier = XGBClassifier(
        n_estimators=300,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.9,
        objective="binary:logistic",
        eval_metric="logloss",
        scale_pos_weight=scale_pos_weight,
        random_state=42,
        n_jobs=-1,
        tree_method="hist",
    )

    steps = []

    if use_thermal_gap:
        steps.append(
            (
                "feature_engineering",
                FunctionTransformer(
                    add_thermal_gap,
                    validate=False,
                ),
            )
        )

    steps.extend(
        [
            ("preprocessor", preprocessor),
            ("classifier", classifier),
        ]
    )

    return Pipeline(steps=steps)
