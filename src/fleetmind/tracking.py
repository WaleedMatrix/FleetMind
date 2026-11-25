"""Optional experiment tracking in a local SQLite store."""

import json
from importlib.metadata import version
from math import isfinite
from pathlib import Path

from sqlalchemy.engine import URL

from fleetmind.model_monitoring import hash_file


def software_versions():
    packages = ("xgboost", "scikit-learn", "numpy", "pandas", "joblib")
    return {name: version(name) for name in packages}


def track(directory, *, name, lineage, metrics, artifacts):
    try:
        from mlflow.tracking import MlflowClient
    except ImportError as exc:
        raise RuntimeError("Install requirements-mlops.txt to enable MLflow.") from exc
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    uri = URL.create("sqlite", database=(directory / "tracking.sqlite3").as_posix())
    client = MlflowClient(tracking_uri=uri.render_as_string(hide_password=False))
    experiment = client.get_experiment_by_name("FleetMind experiments")
    experiment_id = (
        experiment.experiment_id
        if experiment
        else client.create_experiment(
            "FleetMind experiments",
            artifact_location=(directory / "artifacts").as_uri(),
        )
    )
    run = client.create_run(
        experiment_id,
        run_name=name,
        tags={
            "fleetmind.provenance": lineage["provenance"],
            "fleetmind.promotion": "manual_review",
        },
    )
    run_id = run.info.run_id
    try:
        artifacts = list(artifacts)
        metadata = {
            **lineage,
            "recording_software": software_versions(),
            "artifact_sha256": {file.name: hash_file(file) for file in artifacts},
        }
        for key in ("dataset", "dataset_sha256", "model_version", "split_seed"):
            if key in metadata:
                client.log_param(run_id, key, metadata[key])
        for key, value in metrics.items():
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and isfinite(value)
            ):
                client.log_metric(run_id, key, float(value))
        client.log_text(
            run_id, json.dumps(metadata, indent=2, allow_nan=False), "lineage.json"
        )
        for artifact in artifacts:
            client.log_artifact(run_id, str(artifact))
    except Exception:
        client.set_terminated(run_id, "FAILED")
        raise
    client.set_terminated(run_id)
    return run_id
