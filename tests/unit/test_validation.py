import numpy as np
from sklearn.dummy import DummyClassifier

from fleetmind.evaluation.validation import evaluate_model


def test_evaluate_model_returns_expected_metrics():
    X = np.arange(10).reshape(-1, 1)
    y = np.array([0] * 8 + [1] * 2)

    model = DummyClassifier(strategy="prior")
    model.fit(X, y)

    results = evaluate_model(model, X, y)

    assert results["accuracy"] == 0.8
    assert results["precision"] == 0.0
    assert results["recall"] == 0.0
    assert results["f1"] == 0.0
    assert results["average_precision"] == 0.2
    assert results["confusion_matrix"] == [[8, 0], [2, 0]]
