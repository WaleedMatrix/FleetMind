"""Publish mean absolute SHAP for a reproducible AI4I training sample."""

import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import shap

from fleetmind.config import MODEL_VERSION
from fleetmind.data.split import RANDOM_STATE, TEST_SIZE, load_dataset, split_dataset
from fleetmind.explainability import METHOD, OUTPUT_UNIT, ModelExplainer

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_SIZE = 512
SAMPLE_SEED = 42


def main() -> None:
    dataset_path = ROOT / "data" / "raw" / "ai4i2020.csv"
    model_path = ROOT / "artifacts" / "models" / f"{MODEL_VERSION}.joblib"
    metadata = json.loads(model_path.with_suffix(".metadata.json").read_text())
    dataset_sha256 = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    if (
        dataset_sha256 != metadata["dataset_sha256"]
        or metadata["model_version"] != MODEL_VERSION
    ):
        raise ValueError("The dataset must match the frozen model's training metadata")

    training, _, labels, _ = split_dataset(load_dataset(dataset_path))
    if len(training) != metadata["training_observations"] or (
        int(labels.sum()) != metadata["training_failures"]
    ):
        raise ValueError("The training partition does not match the frozen metadata")

    explainer = ModelExplainer(joblib.load(model_path), MODEL_VERSION)
    sample = training.sample(n=SAMPLE_SIZE, random_state=SAMPLE_SEED)
    explanation = explainer.compute(sample)
    importance = np.abs(explanation.grouped).mean(axis=0)
    report = {
        "model_version": MODEL_VERSION,
        "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "dataset_sha256": dataset_sha256,
        "dataset_split": "training",
        "split_seed": RANDOM_STATE,
        "holdout_fraction": TEST_SIZE,
        "sample_size": SAMPLE_SIZE,
        "sample_seed": SAMPLE_SEED,
        "method": METHOD,
        "output_unit": OUTPUT_UNIT,
        "shap_version": shap.__version__,
        "features": [
            {
                "name": group.name,
                "label": group.label,
                "transformed_features": list(group.transformed_features),
                "mean_absolute_shap": float(value),
            }
            for group, value in zip(explainer.groups, importance, strict=True)
        ],
    }
    output = ROOT / "reports" / f"global_shap_{MODEL_VERSION}.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {output.name} from {len(sample)} training observations.")


if __name__ == "__main__":
    main()
