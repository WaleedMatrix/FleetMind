"""Trust anchors for FleetMind's frozen release model."""

from hashlib import file_digest
from pathlib import Path

from fleetmind.config import MODEL_VERSION

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = PROJECT_ROOT / "artifacts" / "models" / f"{MODEL_VERSION}.joblib"
ARTIFACTS = {
    MODEL_PATH: "8dcaddd194de846612b68fa42e34171003cc24457faaddad1f6c5c33ce0978f6",
    MODEL_PATH.with_suffix(
        ".metadata.json"
    ): "fd209f1abe9837a202747803b5f07c350d7dc0502c16d6a9de56e795bae0e3de",
}


def verify_artifacts():
    for path, expected in ARTIFACTS.items():
        with path.open("rb") as stream:
            measured = file_digest(stream, "sha256").hexdigest()
        if measured != expected:
            raise ValueError(f"Frozen artifact digest mismatch: {path.name}")
    return {path.name: digest for path, digest in ARTIFACTS.items()}
