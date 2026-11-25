"""Exact pgvector cosine ranking, PostgreSQL FTS, and reciprocal rank fusion."""

from time import perf_counter
from typing import Literal

from sqlalchemy import cast, func, literal, select
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.orm import Session

from fleetmind.knowledge.embeddings import Embedder, EmbeddingUnavailable
from fleetmind.knowledge.models import Chunk, ChunkEmbedding, Document
from fleetmind.knowledge.schemas import (
    EmbeddingProfile,
    SearchDiagnostics,
    SearchFilters,
    SearchHit,
    SearchRequest,
    SearchResponse,
    SourceCitation,
)
from fleetmind.observability import timed

RRF_CONSTANT = 60


def document_conditions(filters: SearchFilters):
    conditions = []
    if filters.document_ids:
        conditions.append(Document.id.in_(filters.document_ids))
    for key in ("category", "source_kind", "source_ref"):
        value = getattr(filters, key)
        if value is not None:
            conditions.append(getattr(Document, key) == value)
    return conditions


def reciprocal_rank_fusion(
    *rankings: list[str],
    constant: int = RRF_CONSTANT,
) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, key in enumerate(dict.fromkeys(ranking), 1):
            scores[key] = scores.get(key, 0.0) + 1 / (constant + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


@timed("retrieval", log=True)
def search(
    db: Session,
    request: SearchRequest,
    embedder: Embedder,
    *,
    lexical: Literal["strict", "expanded"] = "strict",
) -> SearchResponse:
    started = perf_counter()
    diagnostics = SearchDiagnostics(requested_mode=request.mode, used_mode=request.mode)
    keywords: list[tuple[Chunk, Document, float]] = []
    semantics: list[tuple[Chunk, Document, float]] = []
    base = select(Chunk, Document).join(Document, Chunk.document_id == Document.id)
    base = base.where(*document_conditions(request.filters))
    candidate_limit = max(20, request.top_k * 4)

    if db.scalar(select(base.with_only_columns(Chunk.id).exists())):
        if request.mode != "keyword":
            embedding_started = perf_counter()
            try:
                identity = embedder.identity
                diagnostics.embedding_profile = EmbeddingProfile(
                    model=identity.name,
                    revision=identity.revision,
                    dimensions=identity.dimensions,
                )
                matching = base.join(
                    ChunkEmbedding, ChunkEmbedding.chunk_id == Chunk.id
                )
                matching = matching.where(
                    ChunkEmbedding.model_key == identity.key,
                    ChunkEmbedding.dimensions == identity.dimensions,
                )
                if db.scalar(select(matching.with_only_columns(Chunk.id).exists())):
                    query_vector = embedder.encode([request.query])[0]
                    diagnostics.embedding_ms = (
                        perf_counter() - embedding_started
                    ) * 1000
                    sql_started = perf_counter()
                    distance = ChunkEmbedding.embedding.cosine_distance(query_vector)
                    rows = db.execute(
                        matching.add_columns(distance)
                        .order_by(
                            distance.asc(),
                            Chunk.id.asc(),
                        )
                        .limit(candidate_limit)
                    ).all()
                    semantics = [
                        (chunk, document, max(-1.0, min(1.0, 1.0 - score)))
                        for chunk, document, score in rows
                    ]
                    diagnostics.semantic_sql_ms = (perf_counter() - sql_started) * 1000
                else:
                    diagnostics.fallback = "no_compatible_embeddings"
                    raise EmbeddingUnavailable(
                        "No matching embeddings for the configured model."
                    )
            except EmbeddingUnavailable:
                if request.mode == "semantic":
                    raise
                diagnostics.embedding_ms = (perf_counter() - embedding_started) * 1000
                diagnostics.used_mode = "keyword"
                diagnostics.fallback = diagnostics.fallback or "embedding_unavailable"
        if diagnostics.used_mode != "semantic":
            sql_started = perf_counter()
            config = cast(literal("english"), REGCONFIG)
            if lexical == "expanded":
                terms = db.scalar(
                    select(
                        func.tsvector_to_array(func.to_tsvector(config, request.query))
                    )
                )
                # Reuse PostgreSQL's lexemes and bind the quoted OR query as data.
                quoted = " | ".join(
                    "'" + term.replace("'", "''").replace("\\", "\\\\") + "'"
                    for term in (terms or [])[:24]
                )
                query = func.to_tsquery(cast(literal("simple"), REGCONFIG), quoted)
            else:
                query = func.websearch_to_tsquery(config, request.query)
            score = func.ts_rank_cd(Chunk.search_vector, query)
            rows = db.execute(
                base.add_columns(score)
                .where(
                    Chunk.search_vector.op("@@")(query),
                )
                .order_by(score.desc(), Chunk.id.asc())
                .limit(candidate_limit)
            ).all()
            keywords = [
                (chunk, document, float(rank)) for chunk, document, rank in rows
            ]
            diagnostics.keyword_sql_ms = (perf_counter() - sql_started) * 1000

    diagnostics.semantic_candidates = len(semantics)
    diagnostics.keyword_candidates = len(keywords)
    semantic_ids = [chunk.id for chunk, _, _ in semantics]
    keyword_ids = [chunk.id for chunk, _, _ in keywords]
    semantic_scores = {
        chunk.id: (rank, value) for rank, (chunk, _, value) in enumerate(semantics, 1)
    }
    keyword_scores = {
        chunk.id: (rank, value) for rank, (chunk, _, value) in enumerate(keywords, 1)
    }
    records = {
        chunk.id: (chunk, document) for chunk, document, _ in semantics + keywords
    }
    if diagnostics.used_mode == "hybrid":
        ordered = reciprocal_rank_fusion(semantic_ids, keyword_ids)
    else:
        ids = semantic_ids if diagnostics.used_mode == "semantic" else keyword_ids
        ordered = [(key, None) for key in ids]
    hits = []
    for chunk_id, rrf_score in ordered[: request.top_k]:
        chunk, document = records[chunk_id]
        semantic_rank, similarity = semantic_scores.get(chunk_id, (None, None))
        keyword_rank, keyword_score = keyword_scores.get(chunk_id, (None, None))
        hits.append(
            SearchHit(
                citation=SourceCitation(
                    document_id=document.id,
                    chunk_id=chunk.id,
                    title=document.title,
                    section=chunk.section,
                    position=chunk.position,
                    category=document.category,
                    source_kind=document.source_kind,
                    source_ref=document.source_ref,
                ),
                content=chunk.content,
                semantic_similarity=similarity,
                keyword_rank_score=keyword_score,
                rrf_score=rrf_score,
                semantic_rank=semantic_rank,
                keyword_rank=keyword_rank,
            )
        )
    diagnostics.elapsed_ms = (perf_counter() - started) * 1000
    return SearchResponse(results=hits, diagnostics=diagnostics)
