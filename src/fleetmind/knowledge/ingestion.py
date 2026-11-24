"""Transactional knowledge writes shared by the CLI and offline tooling."""

from dataclasses import dataclass
from time import perf_counter
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from fleetmind.knowledge.documents import (
    DocumentFormat,
    chunk_document,
    normalize,
    sha256,
)
from fleetmind.knowledge.embeddings import Embedder
from fleetmind.knowledge.models import Chunk, ChunkEmbedding, Document, IngestionEvent
from fleetmind.knowledge.schemas import DocumentInput

_WRITE_LOCK = 64_152_186_979_204


@dataclass(frozen=True)
class IngestionResult:
    document_id: str
    action: Literal["inserted", "updated", "unchanged"]
    chunks: int
    generated: int
    reused: int
    elapsed_ms: float
    embedding_ms: float


def ingest(
    db: Session,
    spec: DocumentInput,
    text: str,
    format: DocumentFormat,
    embedder: Embedder,
    *,
    chunk_size: int = 100,
    chunk_overlap: int = 15,
) -> IngestionResult:
    started = perf_counter()
    normalized = normalize(text)
    digest = sha256(normalized)
    drafts = chunk_document(
        spec.id, normalized, spec.title, format, chunk_size, chunk_overlap
    )
    desired = {draft.id: draft for draft in drafts}

    # Keep competing administrative writes atomic while readers see committed content.
    db.execute(select(func.pg_advisory_xact_lock(_WRITE_LOCK)))
    document = db.get(Document, spec.id)
    duplicate = db.scalar(
        select(Document.id).where(
            Document.content_hash == digest,
            Document.id != spec.id,
        )
    )
    if duplicate:
        raise ValueError(
            f"Duplicate normalized content already belongs to {duplicate}."
        )

    profile = embedder.identity
    key = profile.key
    existing = {
        row.id: row
        for row in db.scalars(select(Chunk).where(Chunk.document_id == spec.id))
    }
    indexed = set(
        db.scalars(
            select(ChunkEmbedding.chunk_id).where(
                ChunkEmbedding.chunk_id.in_(desired),
                ChunkEmbedding.model_key == key,
            )
        )
    )
    missing = [draft for draft in drafts if draft.id not in indexed]
    metadata = {
        **spec.model_dump(exclude={"id"}),
        "format": format,
        "content_hash": digest,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
    }
    if (
        document is not None
        and not missing
        and existing.keys() == desired.keys()
        and all(existing[draft.id].position == draft.position for draft in drafts)
        and all(getattr(document, field) == value for field, value in metadata.items())
    ):
        return IngestionResult(
            spec.id,
            "unchanged",
            len(drafts),
            0,
            len(drafts),
            (perf_counter() - started) * 1000,
            0.0,
        )

    needed = {draft.input_hash: draft.embedding_input for draft in missing}
    cache = {}
    if needed:
        cache = dict(
            db.execute(
                select(ChunkEmbedding.input_hash, ChunkEmbedding.embedding)
                .where(
                    ChunkEmbedding.model_key == key,
                    ChunkEmbedding.input_hash.in_(needed),
                )
            .ext(distinct_on(ChunkEmbedding.input_hash))
                .order_by(ChunkEmbedding.input_hash, ChunkEmbedding.chunk_id)
            ).all()
        )
    fresh = {digest: value for digest, value in needed.items() if digest not in cache}
    embedding_started = perf_counter()
    if fresh:
        vectors = embedder.encode(list(fresh.values()))
        cache.update(zip(fresh, vectors, strict=True))
    embedding_ms = (perf_counter() - embedding_started) * 1000 if fresh else 0.0

    action: Literal["inserted", "updated"] = (
        "inserted" if document is None else "updated"
    )
    if document is None:
        document = Document(id=spec.id, **metadata)
        db.add(document)
    else:
        for field, value in metadata.items():
            setattr(document, field, value)
        document.updated_at = func.now()
    db.flush()

    for obsolete in existing.keys() - desired.keys():
        db.delete(existing[obsolete])
    for draft in drafts:
        if draft.id in existing:
            existing[draft.id].position = draft.position
        else:
            db.add(
                Chunk(
                    id=draft.id,
                    document_id=spec.id,
                    position=draft.position,
                    section=draft.section,
                    content=draft.content,
                    content_hash=draft.content_hash,
                )
            )
    db.flush()
    for draft in missing:
        db.add(
            ChunkEmbedding(
                chunk_id=draft.id,
                model_key=key,
                model_name=profile.name,
                model_revision=profile.revision,
                dimensions=profile.dimensions,
                input_hash=draft.input_hash,
                embedding=cache[draft.input_hash],
            )
        )
    db.flush()

    elapsed_ms = (perf_counter() - started) * 1000
    reused = len(drafts) - len(fresh)
    db.add(
        IngestionEvent(
            document_id=spec.id,
            action=action,
            content_hash=digest,
            model_key=key,
            chunk_count=len(drafts),
            generated=len(fresh),
            reused=reused,
            elapsed_ms=elapsed_ms,
        )
    )
    return IngestionResult(
        spec.id,
        action,
        len(drafts),
        len(fresh),
        reused,
        elapsed_ms,
        embedding_ms,
    )


def remove(db: Session, document_id: str) -> bool:
    started = perf_counter()
    db.execute(select(func.pg_advisory_xact_lock(_WRITE_LOCK)))
    document = db.get(Document, document_id)
    if document is None:
        return False
    count = db.scalar(
        select(func.count())
        .select_from(Chunk)
        .where(
            Chunk.document_id == document_id,
        )
    )
    db.add(
        IngestionEvent(
            document_id=document_id,
            action="removed",
            content_hash=document.content_hash,
            chunk_count=count,
            generated=0,
            reused=0,
            elapsed_ms=(perf_counter() - started) * 1000,
        )
    )
    db.delete(document)
    return True
