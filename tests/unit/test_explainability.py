from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest
from scipy.special import expit

from fleetmind.config import MODEL_VERSION
from fleetmind.data.split import FEATURES
from fleetmind.explainability import ExplanationUnavailable, ModelExplainer
from fleetmind.features.engineering import THERMAL_GAP

MODEL_PATH = (
    Path(__file__).resolve().parents[2]
    / "artifacts"
    / "models"
    / f"{MODEL_VERSION}.joblib"
)


@pytest.fixture(scope="module")
def frozen():
    pipeline = joblib.load(MODEL_PATH)
    return pipeline, ModelExplainer(pipeline, MODEL_VERSION)


@pytest.fixture
def readings():
    return pd.DataFrame(
        [
            ["L", 300.0, 310.25, 1500, 40.5, 120],
            ["H", 301.2, 313.7, 1180, 65.1, 211.3],
            ["M", 299.2, 308.1, 1420.4, 45.5, 80.1],
        ],
        columns=FEATURES,
    )


def test_explainer_uses_fitted_transformation_and_order(frozen, readings):
    pipeline, explainer = frozen
    batch = explainer.compute(readings)
    expected = [
        "numeric__Air temperature [K]",
        "numeric__Process temperature [K]",
        "numeric__Rotational speed [rpm]",
        "numeric__Torque [Nm]",
        "numeric__Tool wear [min]",
        f"numeric__{THERMAL_GAP}",
        "categorical__Type_H",
        "categorical__Type_L",
        "categorical__Type_M",
    ]
    assert list(explainer.transformed_features) == expected
    assert [group.name for group in explainer.groups] == [*FEATURES, THERMAL_GAP]
    assert explainer.groups[0].transformed_features == tuple(expected[-3:])
    np.testing.assert_allclose(
        batch.transformed,
        pipeline[:-1].transform(readings),
        rtol=0,
        atol=0,
    )
    np.testing.assert_allclose(batch.transformed[:, 5], [10.25, 12.5, 8.9])
    np.testing.assert_array_equal(
        batch.transformed[:, 6:], [[0, 1, 0], [1, 0, 0], [0, 0, 1]]
    )
    with pytest.raises(ExplanationUnavailable, match="ordered inference inputs"):
        explainer.compute(readings[FEATURES[::-1]])


def test_explanations_add_to_raw_output_not_score(frozen, readings):
    pipeline, explainer = frozen
    batch = explainer.compute(readings)
    expected_margin = pipeline.named_steps["classifier"].predict(
        pipeline[:-1].transform(readings),
        output_margin=True,
    )
    score = pipeline.predict_proba(readings)[:, 1]
    np.testing.assert_allclose(batch.raw_output, expected_margin, rtol=0, atol=0)
    for values in [batch.contributions, batch.grouped]:
        np.testing.assert_allclose(
            batch.baseline + values.sum(axis=1), expected_margin, rtol=1e-5, atol=2e-5
        )
    np.testing.assert_allclose(
        batch.grouped[:, 0], batch.contributions[:, -3:].sum(axis=1)
    )
    np.testing.assert_allclose(expit(batch.raw_output), score, rtol=1e-6, atol=1e-7)
