"""Add telemetry receipts without rewriting existing prediction history."""

import sqlalchemy as sa
from alembic import op

revision = "0005_telemetry_assessments"
down_revision = "0004_copilot_conversations"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "telemetry_assessments",
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column("prediction_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["prediction_id"],
            ["prediction_history.id"],
            name="fk_telemetry_prediction",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("schema_version = 1", name="ck_telemetry_schema_version"),
    )
    op.create_index(
        "ix_telemetry_ingested_at", "telemetry_assessments", ["ingested_at"]
    )
    op.create_index(
        "ix_telemetry_assessed_at", "telemetry_assessments", ["assessed_at"]
    )


def downgrade():
    raise RuntimeError(
        "Downgrading would discard durable telemetry deduplication records."
    )
