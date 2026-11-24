"""PostgreSQL-only knowledge tables, separate from the portable prediction metadata."""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class KnowledgeBase(DeclarativeBase):
    pass


class Document(KnowledgeBase):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        CheckConstraint("format IN ('markdown', 'text')", name="ck_kdoc_format"),
        CheckConstraint(
            "source_kind IN ('project', 'model_metadata', 'general_guidance', "
            "'reference')",
            name="ck_kdoc_source_kind",
        ),
        CheckConstraint(
            "chunk_size > 0 AND chunk_overlap >= 0 AND chunk_overlap < chunk_size",
            name="ck_kdoc_chunk_settings",
        ),
        Index("ix_kdoc_category", "category"),
        Index("ix_kdoc_source_kind", "source_kind"),
        Index("ix_kdoc_source_ref", "source_ref"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(64))
    source_kind: Mapped[str] = mapped_column(String(20))
    source_ref: Mapped[str] = mapped_column(String(240))
    format: Mapped[str] = mapped_column(String(8))
    content_hash: Mapped[str] = mapped_column(String(64), unique=True)
    chunk_size: Mapped[int] = mapped_column(Integer)
    chunk_overlap: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Chunk(KnowledgeBase):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        CheckConstraint("position >= 0", name="ck_kchunk_position"),
        UniqueConstraint(
            "document_id",
            "position",
            name="uq_kchunk_document_position",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index("ix_kchunk_search", "search_vector", postgresql_using="gin"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey(
            "knowledge_documents.id", name="fk_kchunk_document", ondelete="CASCADE"
        )
    )
    position: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('english'::regconfig, section || ' ' || content)",
            persisted=True,
        ),
    )


class ChunkEmbedding(KnowledgeBase):
    __tablename__ = "knowledge_embeddings"
    __table_args__ = (
        CheckConstraint(
            "dimensions BETWEEN 1 AND 2000 AND vector_dims(embedding) = dimensions",
            name="ck_kembedding_dimensions",
        ),
        Index("ix_kembedding_profile_input", "model_key", "input_hash"),
    )

    chunk_id: Mapped[str] = mapped_column(
        ForeignKey(
            "knowledge_chunks.id", name="fk_kembedding_chunk", ondelete="CASCADE"
        ),
        primary_key=True,
    )
    model_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    model_name: Mapped[str] = mapped_column(String(160))
    model_revision: Mapped[str] = mapped_column(String(128))
    dimensions: Mapped[int] = mapped_column(Integer)
    input_hash: Mapped[str] = mapped_column(String(64))
    embedding: Mapped[list[float]] = mapped_column(Vector())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class IngestionEvent(KnowledgeBase):
    __tablename__ = "knowledge_ingestion_events"
    __table_args__ = (
        CheckConstraint(
            "action IN ('inserted', 'updated', 'removed')", name="ck_kevent_action"
        ),
        CheckConstraint(
            "chunk_count >= 0 AND generated >= 0 AND reused >= 0 AND elapsed_ms >= 0",
            name="ck_kevent_counts",
        ),
        Index("ix_kevent_document", "document_id", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(8))
    content_hash: Mapped[str] = mapped_column(String(64))
    model_key: Mapped[str | None] = mapped_column(String(64))
    chunk_count: Mapped[int] = mapped_column(Integer)
    generated: Mapped[int] = mapped_column(Integer)
    reused: Mapped[int] = mapped_column(Integer)
    elapsed_ms: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
