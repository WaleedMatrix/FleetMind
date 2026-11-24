"""Evaluate frozen document relevance judgments at ranked chunk positions."""

import argparse
import hashlib
import json
import math
import statistics
from importlib.metadata import version
from pathlib import Path
from time import perf_counter

from sqlalchemy import select, text

from fleetmind.db.database import SessionLocal
from fleetmind.knowledge.embeddings import SentenceEmbedder
from fleetmind.knowledge.models import Document
from fleetmind.knowledge.retrieval import RRF_CONSTANT, search
from fleetmind.knowledge.schemas import SearchFilters, SearchRequest

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "docs" / "knowledge"
MODES = ("semantic", "keyword", "hybrid")


def score(ranked: list[str], expected: set[str], k: int) -> dict:
    seen = set()
    ranks = []
    for position, document_id in enumerate(ranked[:k], 1):
        if document_id in expected and document_id not in seen:
            ranks.append(position)
        seen.add(document_id)
    dcg = sum(1 / math.log2(rank + 1) for rank in ranks)
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(k, len(expected)) + 1))
    return {
        "recall": len(ranks) / len(expected),
        "reciprocal_rank": 1 / ranks[0] if ranks else 0.0,
        "ndcg": dcg / ideal,
    }


def percentiles(values: list[float]) -> dict:
    sorted_values = sorted(values)
    return {
        "p50": round(statistics.median(values), 3),
        "p95": round(sorted_values[math.ceil(0.95 * len(values)) - 1], 3),
    }


def evaluate(top_k: int) -> dict:
    raw_queries = (CORPUS / "retrieval-evaluation.json").read_bytes()
    cases = json.loads(raw_queries)
    manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    scope = SearchFilters(document_ids=[doc["id"] for doc in manifest])
    if any(set(case["relevant"]) - set(scope.document_ids) for case in cases):
        raise ValueError("Evaluation labels reference a document outside the corpus.")

    embedder = SentenceEmbedder()
    start = perf_counter()
    profile = embedder.identity
    embedder.encode(["FleetMind maintenance knowledge"])
    warmup_ms = (perf_counter() - start) * 1000
    report = {
        "evaluation_sha256": hashlib.sha256(raw_queries).hexdigest(),
        "queries": len(cases),
        "answerable": sum(bool(case["relevant"]) for case in cases),
        "out_of_domain": sum(not case["relevant"] for case in cases),
        "top_k_chunks": top_k,
        "rrf_constant": RRF_CONSTANT,
        "embedding": {
            "model": profile.name,
            "revision": profile.revision,
            "dimensions": profile.dimensions,
        },
        "encoder_warmup_ms": round(warmup_ms, 3),
        "encoder_dependencies": {
            package: version(package)
            for package in ("sentence-transformers", "transformers", "torch")
        },
        "modes": {},
    }
    with SessionLocal() as db:
        report["postgresql"] = db.scalar(text("SHOW server_version"))
        report["pgvector"] = db.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )
        docs = db.scalars(select(Document).where(Document.id.in_(scope.document_ids)))
        indexed = {doc.id: doc for doc in docs}
        if set(scope.document_ids) != indexed.keys():
            raise ValueError("Seed the complete starter corpus before evaluation.")
        report["indexed_documents"] = {
            key: {
                "sha256": doc.content_hash,
                "chunk_size": doc.chunk_size,
                "overlap": doc.chunk_overlap,
            }
            for key, doc in sorted(indexed.items())
        }
        for mode in MODES:
            report["modes"][mode] = evaluate_mode(
                db, embedder, cases, scope, mode, top_k
            )
    return report


def evaluate_mode(db, embedder, cases, scope, mode, top_k):
    timings = {
        key: []
        for key in ("elapsed_ms", "embedding_ms", "semantic_sql_ms", "keyword_sql_ms")
    }
    metrics = []
    misses = []
    ood_with_results = []
    details = []
    relevant_at_one = 0
    for case in cases:
        result = search(
            db,
            SearchRequest(
                query=case["query"],
                top_k=top_k,
                mode=mode,
                filters=scope,
            ),
            embedder,
        )
        if result.diagnostics.used_mode != mode or result.diagnostics.fallback:
            raise ValueError(f"Benchmark {mode} was unavailable for {case['id']}.")
        ranked = [hit.citation.document_id for hit in result.results]
        for key in timings:
            timings[key].append(getattr(result.diagnostics, key))
        details.append({"id": case["id"], "top_documents": ranked})
        if case["relevant"]:
            expected = set(case["relevant"])
            metrics.append(score(ranked, expected, top_k))
            if ranked and ranked[0] in expected:
                relevant_at_one += 1
            if expected.isdisjoint(ranked):
                misses.append(case["id"])
        elif ranked:
            ood_with_results.append(case["id"])

    return {
        **{
            key: round(statistics.mean(row[key] for row in metrics), 6)
            for key in ("recall", "reciprocal_rank", "ndcg")
        },
        "answerable_with_relevant_rank_one": relevant_at_one,
        "answerable_misses": misses,
        "out_of_domain_with_results": ood_with_results,
        "latency_ms": {key: percentiles(values) for key, values in timings.items()},
        "per_query": details,
    }


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--top-k", type=int, default=5, choices=range(1, 21))
    cli.add_argument("--output", type=Path, help="New report path. Defaults to stdout.")
    args = cli.parse_args()
    report = json.dumps(evaluate(args.top_k), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(report)
    else:
        print(report, end="")


if __name__ == "__main__":
    main()
