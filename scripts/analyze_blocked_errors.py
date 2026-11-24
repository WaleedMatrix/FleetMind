import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    precision_score,
    recall_score,
)

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

# Same held-out groups as blocked-validation fold 5.
val_mask = groups.isin([4, 8])

X_fit = X_train.loc[~val_mask]
X_val = X_train.loc[val_mask]

y_fit = y_train.loc[~val_mask]
y_val = y_train.loc[val_mask]

weight = (y_fit == 0).sum() / (y_fit == 1).sum()

models = {
    "Random Forest": build_random_forest_pipeline(),
    "XGBoost": build_xgboost_pipeline(
        scale_pos_weight=weight,
    ),
}

for name, model in models.items():
    model.fit(X_fit, y_fit)

    print(f"\n=== {name.upper()} ===")

    predictions = pd.Series(
        model.predict(X_val),
        index=X_val.index,
    )

    scores = pd.Series(
        model.predict_proba(X_val)[:, 1],
        index=X_val.index,
    )

    for group in [4, 8]:
        mask = groups.loc[X_val.index] == group

        actual = y_val.loc[mask]
        predicted = predictions.loc[mask]
        probabilities = scores.loc[mask]

        tn, fp, fn, tp = confusion_matrix(
            actual,
            predicted,
            labels=[0, 1],
        ).ravel()

        # Failure-mode labels are used for diagnostics
        # only. They are NOT included in the model features.
        hdf = df.loc[actual.index, "HDF"]

        missed_hdf = int(((actual == 1) & (predicted == 0) & (hdf == 1)).sum())

        print(f"\nUDI group {group}")
        print(f"Observations: {len(actual)}")
        print(f"Actual failures: {int(actual.sum())}")
        print(f"TP: {tp}, FP: {fp}, FN: {fn}, TN: {tn}")
        print(f"Precision: {precision_score(actual, predicted, zero_division=0):.4f}")
        print(f"Recall: {recall_score(actual, predicted, zero_division=0):.4f}")
        print(f"AP: {average_precision_score(actual, probabilities):.4f}")
        print(f"Missed HDF-labeled failures: {missed_hdf}")
