from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)


def evaluate_model(model, X, y):
    """Evaluate a fitted binary classifier using predictions and scores."""
    predictions = model.predict(X)
    scores = model.predict_proba(X)[:, 1]

    return {
        "accuracy": accuracy_score(y, predictions),
        "precision": precision_score(y, predictions, zero_division=0),
        "recall": recall_score(y, predictions, zero_division=0),
        "f1": f1_score(y, predictions, zero_division=0),
        "average_precision": average_precision_score(y, scores),
        "confusion_matrix": confusion_matrix(y, predictions, labels=[0, 1]).tolist(),
    }
