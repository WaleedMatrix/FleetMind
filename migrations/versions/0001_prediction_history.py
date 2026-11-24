"""Establish the baseline for existing or new prediction databases."""

import sqlalchemy as sa
from alembic import context, op

revision = "0001_prediction_history"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = (
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("machine_type", sa.String(1), nullable=False),
        sa.Column("air_temperature_k", sa.Float(), nullable=False),
        sa.Column("process_temperature_k", sa.Float(), nullable=False),
        sa.Column("rotational_speed_rpm", sa.Float(), nullable=False),
        sa.Column("torque_nm", sa.Float(), nullable=False),
        sa.Column("tool_wear_min", sa.Float(), nullable=False),
        sa.Column("failure_score", sa.Float(), nullable=False),
        sa.Column("predicted_failure", sa.Boolean(), nullable=False),
        sa.Column("alert_level", sa.String(20), nullable=False),
        sa.Column("model_version", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    if not context.is_offline_mode():
        inspector = sa.inspect(op.get_bind())
        if inspector.has_table("prediction_history"):
            existing = inspector.get_columns("prediction_history")
            expected = {
                column.name: column.type.compile(dialect=op.get_bind().dialect)
                for column in columns
            }
            actual = {
                column["name"]: column["type"].compile(dialect=op.get_bind().dialect)
                for column in existing
            }
            # PostgreSQL reflects the legacy FLOAT columns as DOUBLE PRECISION.
            if op.get_bind().dialect.name == "postgresql":
                expected = {
                    field: "DOUBLE PRECISION" if sql_type == "FLOAT" else sql_type
                    for field, sql_type in expected.items()
                }
            primary_key = inspector.get_pk_constraint("prediction_history")
            if actual != expected or primary_key["constrained_columns"] != ["id"]:
                raise RuntimeError(
                    "Existing prediction_history is not the FleetMind baseline"
                )
            return

    op.create_table("prediction_history", *columns)


def downgrade() -> None:
    raise RuntimeError("The prediction history baseline is forward-only")
