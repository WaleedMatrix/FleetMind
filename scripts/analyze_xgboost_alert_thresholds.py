import pandas as pd
from sklearn.metrics import (
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import GroupKFold

from fleetmind.data.split import load_dataset, split_dataset
from fleetmind.models.xgboost_model import build_xgboost_pipeline

df = load_dataset("data/raw/ai4i2020.csv")

X_train, _, y_train, _ = split_dataset(df)

groups = ((df.loc[X_train.index, "UDI"] - 1) // 1000).astype(int)

cv = GroupKFold(n_splits=5)

# Store each observation's out-of-fold prediction score.
oof_scores = pd.Series(
    index=X_train.index,
    dtype=float,
)

for fit_idx, val_idx in cv.split(
    X_train,
    y_train,
    groups=groups,
):
    X_fit = X_train.iloc[fit_idx]
    X_val = X_train.iloc[val_idx]

    y_fit = y_train.iloc[fit_idx]

    weight = (y_fit == 0).sum() / (y_fit == 1).sum()

    model = build_xgboost_pipeline(
        scale_pos_weight=weight,
        use_thermal_gap=True,
    )

    model.fit(X_fit, y_fit)

    oof_scores.loc[X_val.index] = model.predict_proba(X_val)[:, 1]

assert not oof_scores.isna().any()

# HDF labels are used strictly for diagnostics.
group4_hdf_mask = (groups == 4) & (df.loc[X_train.index, "HDF"] == 1) & (y_train == 1)

results = []

for threshold in [
    0.1,
    0.2,
    0.3,
    0.4,
    0.5,
    0.6,
    0.7,
    0.8,
    0.9,
]:
    predictions = (oof_scores >= threshold).astype(int)

    tn, fp, fn, tp = confusion_matrix(
        y_train,
        predictions,
        labels=[0, 1],
    ).ravel()

    hdf_recall = (predictions.loc[group4_hdf_mask] == 1).mean()

    results.append(
        {
            "Threshold": threshold,
            "Precision": precision_score(
                y_train,
                predictions,
                zero_division=0,
            ),
            "Recall": recall_score(
                y_train,
                predictions,
                zero_division=0,
            ),
            "F1": f1_score(
                y_train,
                predictions,
                zero_division=0,
            ),
            "TP": int(tp),
            "FP": int(fp),
            "FN": int(fn),
            "TN": int(tn),
            "Alerts": int(tp + fp),
            "Group4_HDF_Recall": hdf_recall,
        }
    )

report = pd.DataFrame(results)

print("=== XGBOOST ALERT THRESHOLD ANALYSIS ===")
print(report.round(4).to_string(index=False))

print("\n=== CURRENT 0.5 THRESHOLD ===")
print(report.loc[report["Threshold"] == 0.5].round(4).to_string(index=False))
