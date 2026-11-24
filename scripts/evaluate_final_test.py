"""Final held-out test evaluation for FleetMind XGBoost v1."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)

from fleetmind.config import (
    HIGH_PRIORITY_THRESHOLD,
    MODEL_NAME,
    MODEL_VERSION,
    PRIMARY_METRIC,
    PRIMARY_THRESHOLD,
    REVIEW_THRESHOLD,
    THRESHOLDS,
    USE_THERMAL_GAP,
)
from fleetmind.data.split import load_dataset, split_dataset
from fleetmind.models.xgboost_model import build_xgboost_pipeline

# ============================================================
# 1. LOAD DATASET AND SPLIT
# ============================================================

df = load_dataset("data/raw/ai4i2020.csv")

X_train, X_test, y_train, y_test = split_dataset(df)

print("=== FINAL TEST DATA ===")
print(f"Training observations: {len(X_train)}")
print(f"Test observations: {len(X_test)}")
print(f"Training failures: {int(y_train.sum())}")
print(f"Test failures: {int(y_test.sum())}")
print(f"Test failure rate: {y_test.mean():.4%}")


# ============================================================
# 2. LOAD FROZEN MODEL CONFIGURATION
# ============================================================

print("\n=== FROZEN MODEL CONFIGURATION ===")
print(f"Model name: {MODEL_NAME}")
print(f"Model version: {MODEL_VERSION}")
print(f"Thermal gap enabled: {USE_THERMAL_GAP}")
print(f"Primary metric: {PRIMARY_METRIC}")
print(f"Review threshold: {REVIEW_THRESHOLD}")
print(f"Primary threshold: {PRIMARY_THRESHOLD}")
print(f"High-priority threshold: {HIGH_PRIORITY_THRESHOLD}")

# Validate the frozen threshold configuration.
assert 0 <= REVIEW_THRESHOLD < PRIMARY_THRESHOLD < HIGH_PRIORITY_THRESHOLD <= 1

assert PRIMARY_METRIC == "average_precision"


# ============================================================
# 3. CALCULATE CLASS IMBALANCE WEIGHT
# ============================================================

# Class weighting uses training labels only.
negative_count = int((y_train == 0).sum())
positive_count = int((y_train == 1).sum())

if positive_count == 0:
    raise ValueError("Training data contains no positive examples.")

scale_pos_weight = negative_count / positive_count

print("\n=== CLASS DISTRIBUTION ===")
print(f"Negative samples: {negative_count}")
print(f"Positive samples: {positive_count}")
print(f"Scale positive weight: {scale_pos_weight:.4f}")


# ============================================================
# 4. BUILD AND TRAIN FINAL MODEL
# ============================================================

model = build_xgboost_pipeline(
    scale_pos_weight=scale_pos_weight,
    use_thermal_gap=USE_THERMAL_GAP,
)

print("\n=== TRAINING FINAL MODEL ===")

# Fit once using the complete training partition.
# The test partition is not used for model fitting.
model.fit(X_train, y_train)

print("Final model training completed.")


# ============================================================
# 5. GENERATE TEST PREDICTION SCORES
# ============================================================

scores = model.predict_proba(X_test)[:, 1]

actual = y_test.to_numpy()

average_precision = average_precision_score(
    actual,
    scores,
)

print("\n=== THRESHOLD-INDEPENDENT PERFORMANCE ===")
print(f"Average precision: {average_precision:.4f}")


# ============================================================
# 6. EVALUATE FROZEN CLASSIFICATION THRESHOLDS
# ============================================================

threshold_results = []

for threshold in THRESHOLDS:
    predictions = (scores >= threshold).astype(int)

    tn, fp, fn, tp = confusion_matrix(
        actual,
        predictions,
        labels=[0, 1],
    ).ravel()

    accuracy = accuracy_score(
        actual,
        predictions,
    )

    precision = precision_score(
        actual,
        predictions,
        zero_division=0,
    )

    recall = recall_score(
        actual,
        predictions,
        zero_division=0,
    )

    f1 = f1_score(
        actual,
        predictions,
        zero_division=0,
    )

    threshold_results.append(
        {
            "threshold": float(threshold),
            "accuracy": float(accuracy),
            "precision": float(precision),
            "recall": float(recall),
            "f1": float(f1),
            "TP": int(tp),
            "FP": int(fp),
            "FN": int(fn),
            "TN": int(tn),
            "alerts": int(tp + fp),
        }
    )


threshold_report = pd.DataFrame(threshold_results)

print("\n=== FINAL TEST THRESHOLD RESULTS ===")

print(threshold_report.round(4).to_string(index=False))


# ============================================================
# 7. PRIMARY THRESHOLD PERFORMANCE
# ============================================================

primary_result = next(
    result for result in threshold_results if result["threshold"] == PRIMARY_THRESHOLD
)

print("\n=== PRIMARY MODEL PERFORMANCE ===")

print(f"Model: {MODEL_NAME}")
print(f"Model version: {MODEL_VERSION}")
print(f"Threshold: {PRIMARY_THRESHOLD}")

print(f"Average precision: {average_precision:.4f}")
print(f"Accuracy: {primary_result['accuracy']:.4f}")
print(f"Precision: {primary_result['precision']:.4f}")
print(f"Recall: {primary_result['recall']:.4f}")
print(f"F1-score: {primary_result['f1']:.4f}")

print("\nConfusion matrix:")

print(
    [
        [
            primary_result["TN"],
            primary_result["FP"],
        ],
        [
            primary_result["FN"],
            primary_result["TP"],
        ],
    ]
)


# ============================================================
# 8. TWO-LEVEL MAINTENANCE ALERT POLICY
# ============================================================

# These tiers are mutually exclusive:
#
# High priority: score >= 0.6
# Review:        0.3 <= score < 0.6
# No alert:      score < 0.3
#
# Threshold values come from the frozen configuration.

alert_tiers = [
    (
        "High priority",
        scores >= HIGH_PRIORITY_THRESHOLD,
    ),
    (
        "Review",
        (scores >= REVIEW_THRESHOLD) & (scores < HIGH_PRIORITY_THRESHOLD),
    ),
    (
        "No alert",
        scores < REVIEW_THRESHOLD,
    ),
]

tier_results = []

for tier_name, mask in alert_tiers:
    observations = int(np.sum(mask))

    failures = int(np.sum(actual[mask]))

    normal = observations - failures

    failure_rate = failures / observations if observations > 0 else 0.0

    tier_results.append(
        {
            "tier": tier_name,
            "observations": observations,
            "actual_failures": failures,
            "normal_observations": normal,
            "failure_rate": float(failure_rate),
        }
    )


tier_report = pd.DataFrame(tier_results)

# Confirm every test observation belongs to exactly one tier.
assert tier_report["observations"].sum() == len(X_test)

assert tier_report["actual_failures"].sum() == int(y_test.sum())

print("\n=== MAINTENANCE ALERT TIERS ===")

print(tier_report.round(4).to_string(index=False))


# ============================================================
# 9. PREPARE REPRODUCIBLE RESULTS
# ============================================================

results = {
    "model_name": MODEL_NAME,
    "model_version": MODEL_VERSION,
    "dataset": "AI4I 2020",
    "use_thermal_gap": USE_THERMAL_GAP,
    "primary_metric": PRIMARY_METRIC,
    "training_observations": int(len(X_train)),
    "test_observations": int(len(X_test)),
    "training_failures": int(y_train.sum()),
    "test_failures": int(y_test.sum()),
    "scale_pos_weight": float(scale_pos_weight),
    "average_precision": float(average_precision),
    "threshold_configuration": {
        "review": REVIEW_THRESHOLD,
        "primary": PRIMARY_THRESHOLD,
        "high_priority": HIGH_PRIORITY_THRESHOLD,
    },
    "primary_threshold_results": primary_result,
    "threshold_results": threshold_results,
    "alert_tiers": tier_results,
}


# ============================================================
# 10. SAVE FINAL TEST RESULTS
# ============================================================

output_path = Path("reports/final_test_metrics.json")

output_path.parent.mkdir(
    parents=True,
    exist_ok=True,
)

# Prevent accidentally overwriting a completed final
# evaluation during later development.
if output_path.exists():
    raise FileExistsError(
        f"Final evaluation already exists: {output_path}. "
        "Preserve the original results rather than "
        "overwriting them."
    )

output_path.write_text(
    json.dumps(results, indent=2) + "\n",
    encoding="utf-8",
)

print("\n=== FINAL EVALUATION COMPLETE ===")
print(f"Model version: {MODEL_VERSION}")
print(f"Results saved to: {output_path}")

print(
    "\nImportant: Do not tune the selected model "
    "or thresholds using these test results."
)
