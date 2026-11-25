"""Add persistent Copilot conversations without changing existing rows."""

import sqlalchemy as sa
from alembic import op

revision = "0004_copilot_conversations"
down_revision = "0003_maintenance_knowledge"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "copilot_conversations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column(
            "archived", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("asset_id", sa.String(64)),
        sa.Column("prediction_id", sa.Integer()),
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
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.asset_id"],
            name="fk_copilot_conversation_asset",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["prediction_id"],
            ["prediction_history.id"],
            name="fk_copilot_conversation_prediction",
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_copilot_conversation_archive_updated",
        "copilot_conversations",
        ["archived", "updated_at", "id"],
    )
    op.create_table(
        "copilot_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(9), nullable=False),
        sa.Column("state", sa.String(12), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("asset_id", sa.String(64)),
        sa.Column("prediction_id", sa.Integer()),
        sa.Column("response_status", sa.String(24)),
        sa.Column("response", sa.JSON(none_as_null=True)),
        sa.Column("provider", sa.String(20)),
        sa.Column("model", sa.String(160)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["copilot_conversations.id"],
            name="fk_copilot_message_conversation",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "conversation_id",
            "request_id",
            "role",
            name="uq_copilot_message_request_role",
        ),
        sa.CheckConstraint(
            "(role = 'user' AND response IS NULL AND response_status IS NULL "
            "AND state IN ('pending', 'completed', 'cancelled', 'failed')) OR "
            "(role = 'assistant' AND state = 'completed' AND response IS NOT NULL "
            "AND response_status IS NOT NULL "
            "AND response_status IN ('answered', 'clarification_required', "
            "'insufficient_evidence', 'unavailable'))",
            name="ck_copilot_message_shape",
        ),
    )
    op.create_index(
        "ix_copilot_message_conversation_id",
        "copilot_messages",
        ["conversation_id", "id"],
    )
    op.create_index(
        "ux_copilot_pending_conversation",
        "copilot_messages",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text("role = 'user' AND state = 'pending'"),
    )


def downgrade():
    raise RuntimeError("Downgrading would discard saved Copilot conversations.")
