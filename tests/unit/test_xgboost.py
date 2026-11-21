import numpy as np
import pandas as pd

from fleetmind.models.xgboost_model import build_xgboost_pipeline


def test_xgboost_pipeline_can_fit_and_predict():
    X = pd.DataFrame(
        {
            "Type": ["L", "M", "H", "L", "M", "H"],
            "Air temperature [K]": [300.0, 301.0, 302.0, 299.0, 303.0, 298.0],
            "Process temperature [K]": [310.0, 311.0, 312.0, 309.0, 313.0, 308.0],
            "Rotational speed [rpm]": [1500, 1400, 1300, 1600, 1200, 1700],
            "Torque [Nm]": [40.0, 45.0, 50.0, 35.0, 55.0, 30.0],
            "Tool wear [min]": [100, 120, 140, 80, 160, 60],
        }
    )

    y = [0, 0, 1, 0, 1, 0]

    model = build_xgboost_pipeline(
        scale_pos_weight=2.0,
    )
    model.fit(X, y)

    predictions = model.predict(X)
    probabilities = model.predict_proba(X)

    assert len(predictions) == len(X)
    assert probabilities.shape == (6, 2)
    assert np.all((probabilities >= 0) & (probabilities <= 1))
