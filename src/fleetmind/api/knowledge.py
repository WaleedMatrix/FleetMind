"""Read-only maintenance knowledge inspection and retrieval."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError, ProgrammingError

from fleetmind.api.dependencies import DBSession
from fleetmind.knowledge.embeddings import (
    EmbeddingInputError,
    EmbeddingSettings,
    EmbeddingUnavailable,
    SentenceEmbedder,
    get_embedder,
)
from fleetmind.knowledge.models import Chunk, ChunkEmbedding, Document
from fleetmind.knowledge.retrieval import document_conditions, search
from fleetmind.knowledge.schemas import (
    Category,
    DocumentDetail,
    DocumentId,
    DocumentInfo,
    EmbeddingProfile,
    KnowledgeStatus,
    SearchFilters,
    SearchRequest,
    SearchResponse,
    SourceKind,
)

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])
logger = logging.getLogger(__name__)
STORE_UNAVAILABLE = (
    "Knowledge storage is unavailable. Check PostgreSQL and its migrations."
)
Encoder = Annotated[SentenceEmbedder, Depends(get_embedder)]
PageSize = Annotated[int, Query(ge=1, le=100)]
PageOffset = Annotated[int, Query(ge=0, le=2_147_483_647)]
StorageError = (OperationalError, ProgrammingError)


@router.get("/documents", response_model=list[DocumentInfo])
def documents(
    db: DBSession,
    limit: PageSize = 20,
    offset: PageOffset = 0,
    category: Category | None = None,
    source_kind: SourceKind | None = None,
):
    filters = SearchFilters(category=category, source_kind=source_kind)
    query = select(Document).where(*document_conditions(filters))
    try:
        return list(db.scalars(query.order_by(Document.id).limit(limit).offset(offset)))
    except StorageError as exc:
        raise HTTPException(status_code=503, detail=STORE_UNAVAILABLE) from exc


@router.get("/documents/{document_id}", response_model=DocumentDetail)
def document_detail(
    document_id: DocumentId,
    db: DBSession,
    limit: PageSize = 20,
    offset: PageOffset = 0,
):
    try:
        document = db.get(Document, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Knowledge document not found.")
        query = select(Chunk).where(Chunk.document_id == document_id)
        return {
            "document": document,
            "chunk_count": db.scalar(
                select(func.count()).select_from(query.subquery())
            ),
            "chunks": list(
                db.scalars(query.order_by(Chunk.position).limit(limit).offset(offset))
            ),
        }
    except StorageError as exc:
        raise HTTPException(status_code=503, detail=STORE_UNAVAILABLE) from exc


@router.post("/search", response_model=SearchResponse)
def search_knowledge(request: SearchRequest, db: DBSession, embedder: Encoder):
    try:
        return search(db, request, embedder)
    except EmbeddingInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EmbeddingUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(status_code=503, detail=STORE_UNAVAILABLE) from exc


@router.get("/status", response_model=KnowledgeStatus)
def status(db: DBSession, embedder: Encoder):
    configured = None
    identity = embedder.loaded_identity
    try:
        settings = EmbeddingSettings.from_environment()
        configured = EmbeddingProfile(
            model=identity.name if identity else settings.name,
            revision=identity.revision if identity else settings.revision,
            dimensions=identity.dimensions if identity else None,
        )
    except EmbeddingUnavailable:
        logger.warning("Invalid embedding configuration")
    base = {"embedding_configured": configured, "encoder_loaded": identity is not None}
    try:
        version = db.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )
        if version is None:
            return KnowledgeStatus(
                state="unavailable",
                documents=0,
                chunks=0,
                indexed_profiles=[],
                detail=STORE_UNAVAILABLE,
                **base,
            )
        docs = db.scalar(select(func.count()).select_from(Document))
        chunks = db.scalar(select(func.count()).select_from(Chunk))
        fields = (
            ChunkEmbedding.model_name,
            ChunkEmbedding.model_revision,
            ChunkEmbedding.dimensions,
        )
        profiles = db.execute(
            select(*fields, func.count()).group_by(*fields).order_by(*fields)
        )
        return KnowledgeStatus(
            state="ready" if chunks else "empty",
            documents=docs,
            chunks=chunks,
            pgvector_version=version,
            indexed_profiles=[
                EmbeddingProfile(
                    model=name,
                    revision=revision,
                    dimensions=dimensions,
                    indexed_chunks=count,
                )
                for name, revision, dimensions, count in profiles
            ],
            **base,
        )
    except StorageError:
        return KnowledgeStatus(
            state="unavailable",
            documents=0,
            chunks=0,
            indexed_profiles=[],
            detail=STORE_UNAVAILABLE,
            **base,
        )
