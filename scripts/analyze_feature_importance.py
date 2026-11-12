import pandas as pd
from sklearn.inspection import permutation_importance
from sklearn.model_selection import train_test_split

from fleetmind.data.split import load_dataset, split_dataset
from fleetmind.models.random_forest import (
    build_random_forest_pipeline,
)

df = load_dataset("data/raw/ai4i2020.csv")

X_train, _, y_train, _ = split_dataset(df)

X_fit, X_val, y_fit, y_val = train_test_split(
    X_train,
    y_train,
    test_size=0.20,
    stratify=y_train,
    random_state=42,
)

model = build_random_forest_pipeline()
model.fit(X_fit, y_fit)

importance = permutation_importance(
    model,
    X_val,
    y_val,
    scoring="average_precision",
    n_repeats=10,
    random_state=42,
    n_jobs=1,
)

results = pd.DataFrame(
    {
        "Feature": X_val.columns,
        "Importance Mean": importance.importances_mean,
        "Importance Std": importance.importances_std,
    }
)

results = results.sort_values(
    "Importance Mean",
    ascending=False,
)

print("=== RANDOM FOREST FEATURE IMPORTANCE ===")
print(results.round(4).to_string(index=False))
