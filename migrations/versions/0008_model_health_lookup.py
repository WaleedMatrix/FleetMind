"""Support source-scoped model observation windows."""

from alembic import op

revision = "0008_model_health_lookup"
down_revision = "0007_application_security"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_prediction_history_model_source_created",
        "prediction_history",
        ["model_version", "source", "created_at", "id"],
    )


def downgrade():
    op.drop_index(
        "ix_prediction_history_model_source_created",
        table_name="prediction_history",
    )
