import pandas as pd

from fleetmind.features.engineering import (
    THERMAL_GAP,
    add_thermal_gap,
)


def test_thermal_gap_is_calculated_correctly():
    X = pd.DataFrame(
        {
            "Air temperature [K]": [300.0, 302.0],
            "Process temperature [K]": [310.0, 309.0],
        }
    )

    transformed = add_thermal_gap(X)

    assert transformed[THERMAL_GAP].tolist() == [10.0, 7.0]
    assert THERMAL_GAP not in X.columns
