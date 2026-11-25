"""Regenerate the frozen model's monitoring baseline from its AI4I training split."""

import json
from pathlib import Path

from fleetmind.api.inference import classify_alert
from fleetmind.config import MODEL_VERSION
from fleetmind.data.split import RANDOM_STATE, TEST_SIZE, load_dataset, split_dataset
from fleetmind.features.engineering import add_thermal_gap
from fleetmind.model_monitoring import (
    CATEGORIES,
    SENSOR_FIELDS,
    Histogram,
    Reference,
    bins,
    category_counts,
    fingerprint,
    hash_file,
    quantile_edges,
)
from fleetmind.services.predictions import MODEL_PATH, PROJECT_ROOT, load_frozen_model


def build(dataset: Path) -> Reference:
    metadata_path = MODEL_PATH.with_suffix(".metadata.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    data_hash = hash_file(dataset)
    if (
        data_hash != metadata["dataset_sha256"]
        or metadata["model_version"] != MODEL_VERSION
    ):
        raise ValueError(
            "Dataset or model version differs from frozen training provenance."
        )
    training, _, labels, _ = split_dataset(load_dataset(dataset))
    if (
        len(training) != metadata["training_observations"]
        or labels.sum() != metadata["training_failures"]
    ):
        raise ValueError("Training partition does not match frozen model metadata.")
    scores = load_frozen_model().predict_proba(training)[:, 1]
    frame = add_thermal_gap(training)
    histograms = []
    for key, column in SENSOR_FIELDS.items():
        values = scores if key == "failure_score" else frame[column].to_numpy()
        edges = quantile_edges(values)
        histograms.append(Histogram(key=key, edges=edges, counts=bins(values, edges)))
    categorized = {
        "machine_type": frame["Type"].tolist(),
        "alert_level": [classify_alert(score) for score in scores],
    }
    for key, categories in CATEGORIES.items():
        histograms.append(
            Histogram(
                key=key,
                categories=list(categories),
                counts=category_counts(categorized[key], categories),
            )
        )
    payload = {
        "schema_version": 1,
        "model_version": MODEL_VERSION,
        "model_sha256": hash_file(MODEL_PATH),
        "metadata_sha256": hash_file(metadata_path),
        "dataset": "UCI AI4I 2020",
        "dataset_sha256": data_hash,
        "split": "stratified_training",
        "split_seed": RANDOM_STATE,
        "holdout_fraction": TEST_SIZE,
        "sample_size": len(training),
        "histograms": [hist.model_dump(mode="json") for hist in histograms],
    }
    return Reference(**payload, reference_sha256=fingerprint(payload))


def main():
    reference = build(PROJECT_ROOT / "data/raw/ai4i2020.csv")
    output = PROJECT_ROOT / "reports" / f"model_reference_{MODEL_VERSION}.json"
    output.write_text(reference.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(f"Saved {output.name} from {reference.sample_size} training records.")


if __name__ == "__main__":
    main()
