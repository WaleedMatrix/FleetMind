"""Frozen configuration for FleetMind XGBoost v1."""

# Model identification
MODEL_VERSION = "xgboost_v1"
MODEL_NAME = "XGBoost + Thermal Gap"

# Feature engineering
USE_THERMAL_GAP = True

# Classification thresholds
REVIEW_THRESHOLD = 0.3
PRIMARY_THRESHOLD = 0.5
HIGH_PRIORITY_THRESHOLD = 0.6

# Primary ranking metric
PRIMARY_METRIC = "average_precision"

# Reproducibility
RANDOM_STATE = 42

# Thresholds evaluated in the final test
THRESHOLDS = (
    REVIEW_THRESHOLD,
    PRIMARY_THRESHOLD,
    HIGH_PRIORITY_THRESHOLD,
)
