"""Compare encoder compatibility independently of a database or model provider."""

import argparse
import json
from importlib.metadata import version
from pathlib import Path

import numpy as np

from fleetmind.knowledge.embeddings import SentenceEmbedder
from scripts.evaluate_knowledge import CORPUS

PACKAGES = ("sentence-transformers", "transformers", "torch", "tokenizers")


def snapshot():
    manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    queries = json.loads(
        (CORPUS / "retrieval-evaluation.json").read_text(encoding="utf-8")
    )
    texts = [case["query"] for case in queries]
    for doc in manifest:
        contents = (CORPUS / doc["file"]).read_text(encoding="utf-8")
        texts += [
            part.strip() for part in contents.split("\n\n") if 50 < len(part) < 550
        ]
    embedder = SentenceEmbedder()
    return {
        "packages": {name: version(name) for name in PACKAGES},
        "identity": embedder.identity.key,
        "vectors": embedder.encode(texts),
    }


def compare(baseline, candidate):
    a, b = np.asarray(baseline["vectors"]), np.asarray(candidate["vectors"])
    if a.shape != b.shape or baseline["identity"] != candidate["identity"]:
        raise ValueError("The comparison requires the same model identity and shape.")
    return {
        "baseline": baseline["packages"],
        "candidate": candidate["packages"],
        "identity": candidate["identity"],
        "vectors": len(a),
        "dimensions": a.shape[1],
        "max_absolute_difference": float(np.max(np.abs(a - b))),
        "minimum_cosine_similarity": float(
            np.min(
                (a * b).sum(axis=1)
                / (np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1))
            )
        ),
    }


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--baseline", type=Path, required=True)
    cli.add_argument("--compare", action="store_true")
    cli.add_argument("--output", type=Path)
    args = cli.parse_args()
    current = snapshot()
    if args.compare:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        report = compare(baseline, current)
        result = json.dumps(report, indent=2) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(result)
        print(result, end="")
        return int(
            report["max_absolute_difference"] > 1e-5
            or report["minimum_cosine_similarity"] < 0.99999
        )
    with args.baseline.open("x", encoding="utf-8") as stream:
        json.dump(current, stream)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
