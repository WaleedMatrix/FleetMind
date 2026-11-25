"""Knowledge input, source references, and retrieval response schemas."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

DocumentId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]
Category = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]
SourceKind = Literal["project", "model_metadata", "general_guidance", "reference"]
SourceReference = Annotated[
    str,
    StringConstraints(
        max_length=240,
        pattern=r"^(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+$",
    ),
]
Mode = Literal["semantic", "keyword", "hybrid"]


class DocumentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: DocumentId
    title: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)
    ]
    category: Category
    source_kind: SourceKind
    source_ref: SourceReference

    @field_validator("source_ref")
    @classmethod
    def validate_reference(cls, value: str) -> str:
        if any(part in {".", ".."} for part in value.split("/")):
            raise ValueError("Source reference must be a logical, relative identifier.")
        return value


class DocumentInfo(DocumentInput):
    model_config = ConfigDict(from_attributes=True)

    format: Literal["markdown", "text"]
    content_hash: str
    chunk_size: int
    chunk_overlap: int
    created_at: datetime
    updated_at: datetime


class ChunkInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    position: int
    section: str
    content: str
    content_hash: str


class DocumentDetail(BaseModel):
    document: DocumentInfo
    chunk_count: int
    chunks: list[ChunkInfo]


class SearchFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_ids: list[DocumentId] = Field(default_factory=list, max_length=20)
    category: Category | None = None
    source_kind: SourceKind | None = None
    source_ref: SourceReference | None = None


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)
    ]
    top_k: int = Field(default=5, ge=1, le=20)
    mode: Mode = "hybrid"
    filters: SearchFilters = Field(default_factory=SearchFilters)

    @field_validator("query")
    @classmethod
    def reject_nul(cls, value: str) -> str:
        if "\0" in value:
            raise ValueError("Search text cannot contain NUL characters.")
        return value


class SourceCitation(BaseModel):
    document_id: DocumentId
    chunk_id: str
    title: str
    section: str
    position: int
    category: Category
    source_kind: SourceKind
    source_ref: SourceReference


class SearchHit(BaseModel):
    citation: SourceCitation
    content: str
    semantic_similarity: float | None = None
    keyword_rank_score: float | None = None
    rrf_score: float | None = None
    semantic_rank: int | None = None
    keyword_rank: int | None = None


class EmbeddingProfile(BaseModel):
    model: str
    revision: str | None = None
    dimensions: int | None = None
    indexed_chunks: int | None = None


class SearchDiagnostics(BaseModel):
    requested_mode: Mode
    used_mode: Mode
    embedding_profile: EmbeddingProfile | None = None
    semantic_candidates: int = 0
    keyword_candidates: int = 0
    elapsed_ms: float = 0.0
    embedding_ms: float = 0.0
    semantic_sql_ms: float = 0.0
    keyword_sql_ms: float = 0.0
    fallback: str | None = None


class SearchResponse(BaseModel):
    results: list[SearchHit]
    diagnostics: SearchDiagnostics


class KnowledgeStatus(BaseModel):
    state: Literal["ready", "empty", "unavailable"]
    documents: int
    chunks: int
    pgvector_version: str | None = None
    embedding_configured: EmbeddingProfile | None = None
    encoder_loaded: bool
    indexed_profiles: list[EmbeddingProfile]
    detail: str | None = None
