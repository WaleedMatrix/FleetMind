"""Check both distributed frozen artifacts before executing the pickle."""

from fleetmind.artifacts import verify_artifacts

if __name__ == "__main__":
    for name, digest in verify_artifacts().items():
        print(f"{digest}  {name}")
