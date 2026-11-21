import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import GroupKFold

from fleetmind.data.split import load_dataset, split_dataset
from fleetmind.models.random_forest import (
    build_random_forest_pipeline,
)
from fleetmind.models.xgboost_model import (
    build_xgboost_pipeline,
)

df = load_dataset("data/raw/ai4i2020.csv")
X_train, _, y_train, _ = split_dataset(df)

# Use UDI only to construct evaluation groups.
# UDI must never enter the model features.
groups = ((df.loc[X_train.index, "UDI"] - 1) // 1000).astype(int)

cv = GroupKFold(n_splits=5)

results = []

for fold, (fit_idx, val_idx) in enumerate(
    cv.split(X_train, y_train, groups=groups),
    start=1,
):
    X_fit = X_train.iloc[fit_idx]
    X_val = X_train.iloc[val_idx]
    y_fit = y_train.iloc[fit_idx]
    y_val = y_train.iloc[val_idx]

    weight = (y_fit == 0).sum() / (y_fit == 1).sum()

    models = {
        "Random Forest": build_random_forest_pipeline(),
        "XGBoost": build_xgboost_pipeline(
            scale_pos_weight=weight,
        ),
    }

    held_out_groups = sorted(groups.iloc[val_idx].unique().tolist())

    for name, model in models.items():
        model.fit(X_fit, y_fit)

        predictions = model.predict(X_val)
        scores = model.predict_proba(X_val)[:, 1]

        results.append(
            {
                "model": name,
                "fold": fold,
                "held_out_groups": str(held_out_groups),
                "failures": int(y_val.sum()),
                "average_precision": average_precision_score(y_val, scores),
                "precision": precision_score(y_val, predictions, zero_division=0),
                "recall": recall_score(y_val, predictions, zero_division=0),
                "f1": f1_score(y_val, predictions, zero_division=0),
            }
        )

results_df = pd.DataFrame(results)

print("=== BLOCKED VALIDATION RESULTS ===")
print(results_df.round(4).to_string(index=False))

print("\n=== MODEL SUMMARY ===")

summary = results_df.groupby("model")[
    ["average_precision", "precision", "recall", "f1"]
].agg(["mean", "std"])

print(summary.round(4).to_string())
