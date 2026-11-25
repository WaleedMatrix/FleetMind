"""Record a retrospective import of the verified frozen model and report."""

import argparse
import json
from pathlib import Path

from fleetmind.model_monitoring import read_reference
from fleetmind.services.predictions import MODEL_PATH, PROJECT_ROOT
from fleetmind.tracking import track


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracking-directory", type=Path, required=True)
    args = parser.parse_args()
    reference = read_reference()
    metadata_path = MODEL_PATH.with_suffix(".metadata.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    report = PROJECT_ROOT / "reports/final_test_metrics.json"
    if metadata["evaluation_report"] != report.relative_to(PROJECT_ROOT).as_posix():
        raise ValueError("Frozen metadata points to a different evaluation report.")
    evaluated = json.loads(report.read_text(encoding="utf-8"))
    if evaluated["model_version"] != reference.model_version:
        raise ValueError("Held-out report version does not match the frozen artifact.")
    run = track(
        args.tracking_directory,
        name="Frozen model lineage retrospective import",
        lineage={
            **metadata,
            "dataset": reference.dataset,
            "split_seed": reference.split_seed,
            "provenance": "retrospective_import",
            "evidence_files": [
                metadata_path.relative_to(PROJECT_ROOT).as_posix(),
                metadata["evaluation_report"],
            ],
            "recorded_at_original_training": False,
        },
        metrics={
            "held_out_average_precision": evaluated["average_precision"],
            **{
                f"held_out_{k}": v
                for k, v in evaluated["primary_threshold_results"].items()
            },
        },
        artifacts=[MODEL_PATH, metadata_path, report],
    )
    print("Recorded retrospective MLflow run", run)


if __name__ == "__main__":
    main()
