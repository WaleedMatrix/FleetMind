"""Compare Copilot retrieval with the preserved 9A corpus and query judgments."""

import argparse
import hashlib
import json
import statistics
from pathlib import Path
from time import perf_counter

from sqlalchemy import select, text

from fleetmind.copilot.relevance import collect_knowledge
from fleetmind.db.database import SessionLocal
from fleetmind.knowledge.embeddings import SentenceEmbedder
from fleetmind.knowledge.models import Document
from fleetmind.knowledge.schemas import SearchFilters
from scripts.evaluate_knowledge import percentiles, score

ROOT = Path(__file__).resolve().parents[1]


def evaluate():
    before = json.loads((ROOT / "reports/knowledge_retrieval_m9a.json").read_text())
    raw = (ROOT / "docs/knowledge/retrieval-evaluation.json").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != before["evaluation_sha256"]:
        raise ValueError("The held-out queries changed since the 9A benchmark.")
    cases = json.loads(raw)
    filters = SearchFilters(document_ids=list(before["indexed_documents"]))
    k = before["top_k_chunks"]
    embedder = SentenceEmbedder()
    profile = embedder.identity
    embedder.encode(["FleetMind knowledge evaluation warmup"])
    report = {
        "evaluation_sha256": digest,
        "queries": len(cases),
        "top_k": k,
        "model": profile.name,
        "revision": profile.revision,
        "before_report": "reports/knowledge_retrieval_m9a.json",
        "modes": {},
    }
    with SessionLocal() as db:
        documents = db.scalars(
            select(Document).where(Document.id.in_(filters.document_ids))
        )
        indexed = {
            doc.id: {
                "sha256": doc.content_hash,
                "chunk_size": doc.chunk_size,
                "overlap": doc.chunk_overlap,
            }
            for doc in documents
        }
        if indexed != before["indexed_documents"]:
            raise ValueError("The indexed corpus differs from the 9A benchmark.")
        report["postgresql"] = db.scalar(text("SHOW server_version"))
        for mode in ("semantic", "keyword", "hybrid"):
            ratings, times, misses, ood, details = [], [], [], [], []
            for case in cases:
                started = perf_counter()
                hits, fallback = collect_knowledge(
                    db,
                    case["query"],
                    [],
                    embedder,
                    top_k=k,
                    mode=mode,
                    filters=filters,
                )
                if fallback:
                    raise ValueError(
                        "The expanded retrieval benchmark lost its encoder."
                    )
                times.append((perf_counter() - started) * 1000)
                ranked = [hit.citation.document_id for hit in hits]
                expected = set(case["relevant"])
                if expected:
                    ratings.append(score(ranked, expected, k))
                    if expected.isdisjoint(ranked):
                        misses.append(case["id"])
                elif ranked:
                    ood.append(case["id"])
                details.append({"id": case["id"], "top_documents": ranked})
            metrics = {
                key: round(statistics.mean(row[key] for row in ratings), 6)
                for key in ("recall", "reciprocal_rank", "ndcg")
            }
            report["modes"][mode] = {
                "before": {key: before["modes"][mode][key] for key in metrics},
                "after": metrics,
                "answerable_misses": misses,
                "out_of_domain_with_results": ood,
                "elapsed_ms": percentiles(times),
                "per_query": details,
            }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = json.dumps(evaluate(), indent=2) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(output)
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
