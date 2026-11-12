import pandas as pd

from fleetmind.data.split import FEATURES, split_dataset


def test_split_preserves_rows_and_columns():
    df = pd.DataFrame(
        {
            "Type": ["L", "M"] * 50,
            "Air temperature [K]": [300.0] * 100,
            "Process temperature [K]": [310.0] * 100,
            "Rotational speed [rpm]": [1500] * 100,
            "Torque [Nm]": [40.0] * 100,
            "Tool wear [min]": [100] * 100,
            "Machine failure": [0] * 90 + [1] * 10,
            "HDF": [0] * 100,
        }
    )

    X_train, X_test, y_train, y_test = split_dataset(df)

    assert len(X_train) == 80
    assert len(X_test) == 20

    assert len(y_train) == 80
    assert len(y_test) == 20

    assert list(X_train.columns) == FEATURES
    assert list(X_test.columns) == FEATURES

    assert "HDF" not in X_train.columns
    assert "Machine failure" not in X_train.columns

    assert y_train.sum() == 8
    assert y_test.sum() == 2
