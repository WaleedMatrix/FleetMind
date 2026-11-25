"""Generate local scraper and Grafana credentials and target discovery files."""

import argparse
import json
import os
from pathlib import Path
from secrets import token_urlsafe


def write_new(path, content):
    try:
        with os.fdopen(
            os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600),
            "w",
            encoding="ascii",
            newline="\n",
        ) as stream:
            stream.write(content + "\n")
    except FileExistsError:
        pass


def targets(ports):
    if not ports:
        return "[]"
    return json.dumps(
        [{"targets": [f"host.docker.internal:{port}" for port in ports]}], indent=2
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path(".env.observability"))
    parser.add_argument("--api-port", type=int, action="append")
    parser.add_argument("--worker-port", type=int, action="append", default=[])
    args = parser.parse_args()
    apis = args.api_port or [8000]
    if any(not 1024 <= port <= 65535 for port in [*apis, *args.worker_port]):
        parser.error("Use ports between 1024 and 65535.")
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    discovery = directory / "targets"
    discovery.mkdir(exist_ok=True)
    write_new(directory / "scrape.token", token_urlsafe(32))
    write_new(directory / "grafana.password", token_urlsafe(32))
    write_new(discovery / "api.json", targets(apis))
    write_new(discovery / "workers.json", targets(args.worker_port))
    print("Observability credentials and initial targets are ready in", directory)
    print("Update target JSON files explicitly if the replica ports change.")


if __name__ == "__main__":
    main()
