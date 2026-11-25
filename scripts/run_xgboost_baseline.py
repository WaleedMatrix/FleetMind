"""Train and evaluate a validation-only baseline, with optional local MLflow."""

import argparse
from math import isfinite
from pathlib import Path
from pprint import pprint
from tempfile import TemporaryDirectory

import joblib
from sklearn.model_selection import train_test_split

from fleetmind.data.split import RANDOM_STATE, load_dataset, split_dataset
from fleetmind.evaluation.validation import evaluate_model
from fleetmind.model_monitoring import hash_file
from fleetmind.models.xgboost_model import build_xgboost_pipeline
from fleetmind.tracking import track

DATASET = Path("data/raw/ai4i2020.csv")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--tracking-directory", type=Path)
    args = cli.parse_args()
    df = load_dataset(DATASET)
    X_train, _, y_train, _ = split_dataset(df)
    X_fit, X_val, y_fit, y_val = train_test_split(
        X_train,
        y_train,
        test_size=0.20,
        stratify=y_train,
        random_state=RANDOM_STATE,
    )
    scale_pos_weight = (y_fit == 0).sum() / (y_fit == 1).sum()
    model = build_xgboost_pipeline(scale_pos_weight=scale_pos_weight)
    model.fit(X_fit, y_fit)
    results = evaluate_model(model, X_val, y_val)

    print("=== XGBOOST VALIDATION ===")
    print(f"Fit observations: {len(X_fit)}")
    print(f"Validation observations: {len(X_val)}")
    print(f"Scale positive weight: {scale_pos_weight:.2f}")
    pprint(results)

    if args.tracking_directory:
        with TemporaryDirectory(prefix="fleetmind-validation-") as scratch:
            artifact = Path(scratch) / "validation-model.joblib"
            joblib.dump(model, artifact)
            estimator = model.steps[-1][1]
            params = {
                key: repr(value)
                if isinstance(value, float) and not isfinite(value)
                else value
                for key, value in estimator.get_params().items()
                if isinstance(value, (str, int, float, bool)) or value is None
            }
            run = track(
                args.tracking_directory,
                name="XGBoost validation experiment",
                lineage={
                    "provenance": "observed_validation_run",
                    "dataset": "UCI AI4I 2020",
                    "dataset_sha256": hash_file(DATASET),
                    "split_seed": RANDOM_STATE,
                    "model_version": "experimental-validation",
                    "features": X_fit.columns.tolist(),
                    "pipeline_steps": [name for name, _ in model.steps],
                    "training_parameters": params,
                    "fit_rows": len(X_fit),
                    "validation_rows": len(X_val),
                    "validation_results": results,
                },
                metrics=results,
                artifacts=[artifact],
            )
            print("Recorded validation MLflow run", run)


if __name__ == "__main__":
    main()
