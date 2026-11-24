import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import StratifiedKFold

from fleetmind.data.split import load_dataset, split_dataset
from fleetmind.models.xgboost_model import build_xgboost_pipeline

df = load_dataset("data/raw/ai4i2020.csv")
X_train, _, y_train, _ = split_dataset(df)

cv = StratifiedKFold(
    n_splits=5,
    shuffle=True,
    random_state=42,
)

fold_results = []

for fold, (fit_idx, val_idx) in enumerate(
    cv.split(X_train, y_train),
    start=1,
):
    X_fit = X_train.iloc[fit_idx]
    X_val = X_train.iloc[val_idx]

    y_fit = y_train.iloc[fit_idx]
    y_val = y_train.iloc[val_idx]

    negative_count = (y_fit == 0).sum()
    positive_count = (y_fit == 1).sum()

    scale_pos_weight = negative_count / positive_count

    model = build_xgboost_pipeline(
        scale_pos_weight=scale_pos_weight,
    )

    model.fit(X_fit, y_fit)

    predictions = model.predict(X_val)
    probabilities = model.predict_proba(X_val)[:, 1]

    fold_results.append(
        {
            "fold": fold,
            "average_precision": average_precision_score(y_val, probabilities),
            "precision": precision_score(y_val, predictions, zero_division=0),
            "recall": recall_score(y_val, predictions, zero_division=0),
            "f1": f1_score(y_val, predictions, zero_division=0),
        }
    )

results = pd.DataFrame(fold_results)

print("=== XGBOOST FIVE-FOLD RESULTS ===")
print(results.round(4).to_string(index=False))

print("\n=== CROSS-VALIDATION SUMMARY ===")

for metric in [
    "average_precision",
    "precision",
    "recall",
    "f1",
]:
    print(
        f"{metric}: {results[metric].mean():.4f} +/- {results[metric].std(ddof=0):.4f}"
    )
