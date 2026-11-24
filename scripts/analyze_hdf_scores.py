import pandas as pd

from fleetmind.data.split import load_dataset, split_dataset
from fleetmind.models.random_forest import (
    build_random_forest_pipeline,
)
from fleetmind.models.xgboost_model import (
    build_xgboost_pipeline,
)

df = load_dataset("data/raw/ai4i2020.csv")
X_train, _, y_train, _ = split_dataset(df)

groups = ((df.loc[X_train.index, "UDI"] - 1) // 1000).astype(int)

# Reproduce blocked-validation fold 5.
held_out = groups.isin([4, 8])

X_fit = X_train.loc[~held_out]
X_val = X_train.loc[held_out]

y_fit = y_train.loc[~held_out]
y_val = y_train.loc[held_out]

weight = (y_fit == 0).sum() / (y_fit == 1).sum()

training_hdf = ((df.loc[y_fit.index, "HDF"] == 1) & (y_fit == 1)).sum()

print(f"HDF-labeled failures in fitting data: {training_hdf}")

group4_index = groups[groups == 4].index
y4 = y_val.loc[group4_index]
hdf4 = df.loc[group4_index, "HDF"]

models = {
    "Random Forest": build_random_forest_pipeline(),
    "XGBoost": build_xgboost_pipeline(
        scale_pos_weight=weight,
    ),
}

for name, model in models.items():
    model.fit(X_fit, y_fit)

    scores = pd.Series(
        model.predict_proba(X_val)[:, 1],
        index=X_val.index,
    )

    group4_scores = scores.loc[group4_index]

    categories = {
        "HDF failures": (y4 == 1) & (hdf4 == 1),
        "Other failures": (y4 == 1) & (hdf4 == 0),
        "Normal observations": y4 == 0,
    }

    rows = []

    for category, mask in categories.items():
        selected = group4_scores.loc[mask]

        rows.append(
            {
                "Category": category,
                "Count": len(selected),
                "Mean score": selected.mean(),
                "Median score": selected.median(),
                "Fraction flagged at 0.5": ((selected >= 0.5).mean()),
            }
        )

    print(f"\n=== {name.upper()} — GROUP 4 ===")

    report = pd.DataFrame(rows)
    print(report.round(4).to_string(index=False))
