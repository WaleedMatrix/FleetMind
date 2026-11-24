"""Train and export the frozen FleetMind XGBoost v1 pipeline."""

import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import sklearn
import xgboost

from fleetmind.config import (
    HIGH_PRIORITY_THRESHOLD,
    MODEL_NAME,
    MODEL_VERSION,
    PRIMARY_THRESHOLD,
    REVIEW_THRESHOLD,
    USE_THERMAL_GAP,
)
from fleetmind.data.split import load_dataset, split_dataset
from fleetmind.models.xgboost_model import build_xgboost_pipeline

# ============================================================
# 1. ARTIFACT CONFIGURATION
# ============================================================

DATA_PATH = Path("data/raw/ai4i2020.csv")
OUTPUT_DIR = Path("artifacts/models")

MODEL_PATH = OUTPUT_DIR / f"{MODEL_VERSION}.joblib"
METADATA_PATH = OUTPUT_DIR / f"{MODEL_VERSION}.metadata.json"

# Avoid accidentally replacing the versioned artifact.
if MODEL_PATH.exists() or METADATA_PATH.exists():
    raise FileExistsError(
        "Model artifact or metadata already exists. Preserve the existing version."
    )


# ============================================================
# 2. LOAD TRAINING PARTITION
# ============================================================

df = load_dataset(DATA_PATH)

X_train, _, y_train, _ = split_dataset(df)

negative_count = int((y_train == 0).sum())
positive_count = int((y_train == 1).sum())

if positive_count == 0:
    raise ValueError("No positive training observations.")

scale_pos_weight = negative_count / positive_count


# ============================================================
# 3. FIT FROZEN PIPELINE
# ============================================================

model = build_xgboost_pipeline(
    scale_pos_weight=scale_pos_weight,
    use_thermal_gap=USE_THERMAL_GAP,
)

print(f"Training {MODEL_NAME}...")
print(f"Training observations: {len(X_train)}")

model.fit(X_train, y_train)


# ============================================================
# 4. SERIALIZE MODEL
# ============================================================

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

joblib.dump(
    model,
    MODEL_PATH,
    compress=3,
)

print(f"Saved model: {MODEL_PATH}")


# ============================================================
# 5. VERIFY SERIALIZATION
# ============================================================

# Only load model artifacts created by trusted code.
loaded_model = joblib.load(MODEL_PATH)

sample = X_train.iloc[:10]

original_scores = model.predict_proba(sample)
loaded_scores = loaded_model.predict_proba(sample)

np.testing.assert_allclose(
    original_scores,
    loaded_scores,
    rtol=1e-7,
    atol=1e-9,
)

print("Serialization verification passed.")


# ============================================================
# 6. SAVE MODEL METADATA
# ============================================================

dataset_hash = hashlib.sha256(DATA_PATH.read_bytes()).hexdigest()

classifier = model.named_steps["classifier"]

parameter_names = [
    "n_estimators",
    "max_depth",
    "learning_rate",
    "subsample",
    "colsample_bytree",
    "objective",
    "eval_metric",
    "random_state",
    "tree_method",
]

classifier_params = classifier.get_params()

metadata = {
    "model_name": MODEL_NAME,
    "model_version": MODEL_VERSION,
    "algorithm": "XGBoost",
    "feature_engineering": {
        "thermal_gap": USE_THERMAL_GAP,
    },
    "input_features": X_train.columns.tolist(),
    "training_observations": int(len(X_train)),
    "training_failures": positive_count,
    "scale_pos_weight": float(scale_pos_weight),
    "model_hyperparameters": {
        name: classifier_params[name] for name in parameter_names
    },
    "thresholds": {
        "review": REVIEW_THRESHOLD,
        "primary": PRIMARY_THRESHOLD,
        "high_priority": HIGH_PRIORITY_THRESHOLD,
    },
    "dataset_sha256": dataset_hash,
    "dependencies": {
        "scikit_learn": sklearn.__version__,
        "xgboost": xgboost.__version__,
        "joblib": joblib.__version__,
    },
    "evaluation_report": "reports/final_test_metrics.json",
}

METADATA_PATH.write_text(
    json.dumps(metadata, indent=2) + "\n",
    encoding="utf-8",
)

print(f"Saved metadata: {METADATA_PATH}")
print("FleetMind XGBoost v1 export completed.")
