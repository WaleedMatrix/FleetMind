import pandas as pd
from sklearn.model_selection import (
    StratifiedKFold,
    cross_validate,
)

from fleetmind.data.split import load_dataset, split_dataset
from fleetmind.models.logistic import build_logistic_pipeline
from fleetmind.models.random_forest import (
    build_random_forest_pipeline,
)

df = load_dataset("data/raw/ai4i2020.csv")

X_train, _, y_train, _ = split_dataset(df)

cv = StratifiedKFold(
    n_splits=5,
    shuffle=True,
    random_state=42,
)

scoring = {
    "average_precision": "average_precision",
    "precision": "precision",
    "recall": "recall",
    "f1": "f1",
}

models = {
    "Logistic Regression": build_logistic_pipeline(),
    "Random Forest": build_random_forest_pipeline(),
}

results = []

for name, model in models.items():
    print(f"\nEvaluating {name}...")

    scores = cross_validate(
        model,
        X_train,
        y_train,
        cv=cv,
        scoring=scoring,
        n_jobs=1,
        error_score="raise",
    )

    row = {"Model": name}

    for metric in scoring:
        values = scores[f"test_{metric}"]

        row[f"{metric}_mean"] = values.mean()
        row[f"{metric}_std"] = values.std()

    results.append(row)

summary = pd.DataFrame(results)

print("\n=== FIVE-FOLD CROSS-VALIDATION ===")
print(summary.round(4).to_string(index=False))
