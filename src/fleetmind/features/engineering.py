import pandas as pd

THERMAL_GAP = "Temperature gap [K]"


def add_thermal_gap(X: pd.DataFrame) -> pd.DataFrame:
    """Create a temperature-difference feature."""

    X = X.copy()

    X[THERMAL_GAP] = X["Process temperature [K]"] - X["Air temperature [K]"]

    return X
