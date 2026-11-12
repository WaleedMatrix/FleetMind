from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split

TARGET = "Machine failure"

FEATURES = [
    "Type",
    "Air temperature [K]",
    "Process temperature [K]",
    "Rotational speed [rpm]",
    "Torque [Nm]",
    "Tool wear [min]",
]

RANDOM_STATE = 42
TEST_SIZE = 0.20


def load_dataset(path: str | Path) -> pd.DataFrame:
    """Load the AI4I dataset from CSV."""
    return pd.read_csv(path)


def split_dataset(df: pd.DataFrame):
    """Create stratified training and held-out test partitions."""
    X = df[FEATURES].copy()
    y = df[TARGET].copy()

    return train_test_split(
        X,
        y,
        test_size=TEST_SIZE,
        stratify=y,
        random_state=RANDOM_STATE,
    )
