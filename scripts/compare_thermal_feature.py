import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import GroupKFold

from fleetmind.data.split import load_dataset, split_dataset
from fleetmind.models.xgboost_model import build_xgboost_pipeline

# ============================================================
# 1. LOAD DATASET
# ============================================================

df = load_dataset("data/raw/ai4i2020.csv")

# Use only the development/training partition.
# Keep the final test set untouched.
X_train, _, y_train, _ = split_dataset(df)

# UDI is used for grouping only, never as a model feature.
groups = ((df.loc[X_train.index, "UDI"] - 1) // 1000).astype(int)

cv = GroupKFold(n_splits=5)

results = []


# ============================================================
# 2. BLOCKED CROSS-VALIDATION
# ============================================================

for fold, (fit_idx, val_idx) in enumerate(
    cv.split(X_train, y_train, groups=groups),
    start=1,
):
    X_fit = X_train.iloc[fit_idx]
    X_val = X_train.iloc[val_idx]

    y_fit = y_train.iloc[fit_idx]
    y_val = y_train.iloc[val_idx]

    # Compute class imbalance weight using training data only.
    negative_count = (y_fit == 0).sum()
    positive_count = (y_fit == 1).sum()

    weight = negative_count / positive_count

    held_out_groups = sorted(groups.iloc[val_idx].unique().tolist())

    # Compare original XGBoost against engineered XGBoost.
    for name, use_gap in [
        ("Baseline", False),
        ("Thermal Gap", True),
    ]:
        model = build_xgboost_pipeline(
            scale_pos_weight=weight,
            use_thermal_gap=use_gap,
        )

        model.fit(X_fit, y_fit)

        predictions = pd.Series(
            model.predict(X_val),
            index=X_val.index,
        )

        scores = model.predict_proba(X_val)[:, 1]

        # ----------------------------------------------------
        # 3. CONFUSION MATRIX
        # ----------------------------------------------------

        tn, fp, fn, tp = confusion_matrix(
            y_val,
            predictions,
            labels=[0, 1],
        ).ravel()

        alerts = int(tp + fp)

        # ----------------------------------------------------
        # 4. GROUP 4 HDF DIAGNOSTIC
        # ----------------------------------------------------

        # HDF is an outcome label used only for evaluation.
        # It must never be included among model features.
        group4_hdf_mask = (
            (groups.loc[X_val.index] == 4)
            & (df.loc[X_val.index, "HDF"] == 1)
            & (y_val == 1)
        )

        hdf_indices = X_val.index[group4_hdf_mask]

        hdf_recall = float("nan")

        if len(hdf_indices) > 0:
            hdf_recall = float((predictions.loc[hdf_indices] == 1).mean())

        # ----------------------------------------------------
        # 5. STORE METRICS
        # ----------------------------------------------------

        results.append(
            {
                "model": name,
                "fold": fold,
                "held_out": str(held_out_groups),
                "AP": average_precision_score(
                    y_val,
                    scores,
                ),
                "Precision": precision_score(
                    y_val,
                    predictions,
                    zero_division=0,
                ),
                "Recall": recall_score(
                    y_val,
                    predictions,
                    zero_division=0,
                ),
                "F1": f1_score(
                    y_val,
                    predictions,
                    zero_division=0,
                ),
                "TP": int(tp),
                "FP": int(fp),
                "FN": int(fn),
                "TN": int(tn),
                "Alerts": alerts,
                "Group4_HDF_recall": hdf_recall,
            }
        )


# ============================================================
# 6. FULL RESULTS
# ============================================================

report = pd.DataFrame(results)

print("\n=== FEATURE ENGINEERING COMPARISON ===")

print(report.round(4).to_string(index=False))


# ============================================================
# 7. MEAN BLOCKED PERFORMANCE
# ============================================================

print("\n=== MEAN BLOCKED PERFORMANCE ===")

mean_metrics = (
    report.groupby("model")[["AP", "Precision", "Recall", "F1"]].mean().round(4)
)

print(mean_metrics.to_string())


# ============================================================
# 8. GROUP 4 HDF RECALL
# ============================================================

print("\n=== GROUP 4 HDF RECALL ===")

hdf_report = report.dropna(subset=["Group4_HDF_recall"])[["model", "Group4_HDF_recall"]]

print(hdf_report.round(4).to_string(index=False))


# ============================================================
# 9. FOLD 5: FALSE ALARM COMPARISON
# ============================================================

print("\n=== FOLD 5: FALSE ALARM COMPARISON ===")

fold5_report = report.loc[
    report["fold"] == 5,
    [
        "model",
        "TP",
        "FP",
        "FN",
        "TN",
        "Alerts",
        "Precision",
        "Recall",
        "F1",
        "Group4_HDF_recall",
    ],
]

print(fold5_report.round(4).to_string(index=False))


# ============================================================
# 10. TOTAL ERRORS ACROSS BLOCKED FOLDS
# ============================================================

print("\n=== TOTAL ERRORS ACROSS BLOCKED FOLDS ===")

total_errors = report.groupby("model")[["TP", "FP", "FN", "TN", "Alerts"]].sum()

print(total_errors.to_string())


# ============================================================
# 11. PERFORMANCE IMPROVEMENT SUMMARY
# ============================================================

print("\n=== THERMAL GAP IMPROVEMENT ===")

baseline = mean_metrics.loc["Baseline"]
engineered = mean_metrics.loc["Thermal Gap"]

for metric in ["AP", "Precision", "Recall", "F1"]:
    difference = engineered[metric] - baseline[metric]

    print(
        f"{metric}: "
        f"{baseline[metric]:.4f} -> "
        f"{engineered[metric]:.4f} "
        f"(change: {difference:+.4f})"
    )
