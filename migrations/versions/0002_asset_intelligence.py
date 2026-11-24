"""Register assets and associate new readings while retaining existing history."""

import sqlalchemy as sa
from alembic import op

revision = "0002_asset_intelligence"
down_revision = "0001_prediction_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("asset_id", sa.String(64), primary_key=True),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("machine_type", sa.String(1), nullable=False),
        sa.Column("location", sa.String(120)),
        sa.Column("description", sa.String(1000)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "machine_type IN ('L', 'M', 'H')", name="ck_assets_machine_type"
        ),
    )
    op.create_index(
        "ix_assets_machine_type_asset_id", "assets", ["machine_type", "asset_id"]
    )
    op.add_column("prediction_history", sa.Column("asset_id", sa.String(64)))
    op.add_column(
        "prediction_history",
        sa.Column("source", sa.String(12), server_default="unknown", nullable=False),
    )
    op.create_foreign_key(
        "fk_prediction_history_asset_id",
        "prediction_history",
        "assets",
        ["asset_id"],
        ["asset_id"],
    )
    op.create_check_constraint(
        "ck_prediction_history_source",
        "prediction_history",
        "source IN ('unknown', 'manual', 'simulated', 'telemetry')",
    )
    op.create_index(
        "ix_prediction_history_asset_id_id", "prediction_history", ["asset_id", "id"]
    )
    op.create_index(
        "ix_prediction_history_asset_alert_id",
        "prediction_history",
        ["asset_id", "alert_level", "id"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrading would discard registered assets and reading provenance"
    )
