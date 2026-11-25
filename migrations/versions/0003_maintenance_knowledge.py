"""Add the PostgreSQL maintenance knowledge tables and pgvector extension."""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import TSVECTOR

revision = "0003_maintenance_knowledge"
down_revision = "0002_asset_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("source_kind", sa.String(20), nullable=False),
        sa.Column("source_ref", sa.String(240), nullable=False),
        sa.Column("format", sa.String(8), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("chunk_size", sa.Integer(), nullable=False),
        sa.Column("chunk_overlap", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("format IN ('markdown', 'text')", name="ck_kdoc_format"),
        sa.CheckConstraint(
            "source_kind IN ('project', 'model_metadata', 'general_guidance', "
            "'reference')",
            name="ck_kdoc_source_kind",
        ),
        sa.CheckConstraint(
            "chunk_size > 0 AND chunk_overlap >= 0 AND chunk_overlap < chunk_size",
            name="ck_kdoc_chunk_settings",
        ),
    )
    for field in ("category", "source_kind", "source_ref"):
        op.create_index(f"ix_kdoc_{field}", "knowledge_documents", [field])
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("document_id", sa.String(64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("section", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "search_vector",
            TSVECTOR,
            sa.Computed(
                "to_tsvector('english'::regconfig, section || ' ' || content)",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.CheckConstraint("position >= 0", name="ck_kchunk_position"),
        sa.UniqueConstraint(
            "document_id",
            "position",
            name="uq_kchunk_document_position",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge_documents.id"],
            name="fk_kchunk_document",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_kchunk_search",
        "knowledge_chunks",
        ["search_vector"],
        postgresql_using="gin",
    )
    op.create_table(
        "knowledge_embeddings",
        sa.Column("chunk_id", sa.String(64), primary_key=True),
        sa.Column("model_key", sa.String(64), primary_key=True),
        sa.Column("model_name", sa.String(160), nullable=False),
        sa.Column("model_revision", sa.String(128), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("embedding", Vector(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["knowledge_chunks.id"],
            name="fk_kembedding_chunk",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "dimensions BETWEEN 1 AND 2000 AND vector_dims(embedding) = dimensions",
            name="ck_kembedding_dimensions",
        ),
    )
    op.create_index(
        "ix_kembedding_profile_input",
        "knowledge_embeddings",
        ["model_key", "input_hash"],
    )
    op.create_table(
        "knowledge_ingestion_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(8), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("model_key", sa.String(64)),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("generated", sa.Integer(), nullable=False),
        sa.Column("reused", sa.Integer(), nullable=False),
        sa.Column("elapsed_ms", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "action IN ('inserted', 'updated', 'removed')", name="ck_kevent_action"
        ),
        sa.CheckConstraint(
            "chunk_count >= 0 AND generated >= 0 AND reused >= 0 AND elapsed_ms >= 0",
            name="ck_kevent_counts",
        ),
    )
    op.create_index(
        "ix_kevent_document", "knowledge_ingestion_events", ["document_id", "id"]
    )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrading would discard maintenance knowledge and ingestion history"
    )
