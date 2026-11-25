"""Persist a commit-ordered telemetry cursor and worker diagnostics."""

import sqlalchemy as sa
from alembic import op

revision = "0006_telemetry_live_monitoring"
down_revision = "0005_telemetry_assessments"
branch_labels = None
depends_on = None


def upgrade():
    # Serialize the one-time backfill with all receipt inserts.
    op.execute("LOCK TABLE telemetry_assessments IN SHARE ROW EXCLUSIVE MODE")
    op.create_table(
        "telemetry_stream_cursor",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("position", sa.BigInteger(), nullable=False),
    )
    op.create_table(
        "telemetry_stream_events",
        sa.Column("position", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("event_id", sa.Uuid(), nullable=False, unique=True),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["telemetry_assessments.event_id"],
            name="fk_telemetry_stream_event",
        ),
    )
    op.execute("""
        INSERT INTO telemetry_stream_events (position, event_id)
        SELECT row_number() OVER (ORDER BY prediction_id), event_id
        FROM telemetry_assessments
    """)
    op.execute("""
        INSERT INTO telemetry_stream_cursor (id, position)
        SELECT 1, coalesce(max(position), 0) FROM telemetry_stream_events
    """)
    op.execute("""
        CREATE FUNCTION fleetmind_sequence_telemetry() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            WITH next_position AS (
                UPDATE telemetry_stream_cursor SET position = position + 1
                WHERE id = 1 RETURNING position
            )
            INSERT INTO telemetry_stream_events (position, event_id)
            SELECT position, NEW.event_id FROM next_position;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Telemetry stream cursor is missing';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER fleetmind_telemetry_stream_insert
        AFTER INSERT ON telemetry_assessments FOR EACH ROW
        EXECUTE FUNCTION fleetmind_sequence_telemetry()
    """)
    op.create_table(
        "telemetry_worker_checkpoints",
        sa.Column("worker_id", sa.Uuid(), primary_key=True),
        sa.Column("sampled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("running", sa.Boolean(), nullable=False),
        sa.Column("broker_ok", sa.Boolean()),
        sa.Column("lag", sa.BigInteger()),
        sa.Column("counts", sa.JSON(), nullable=False),
        sa.Column("timings", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_telemetry_workers_sampled", "telemetry_worker_checkpoints", ["sampled_at"]
    )
    op.create_table(
        "telemetry_metric_totals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("counts", sa.JSON(), nullable=False),
    )
    op.execute("INSERT INTO telemetry_metric_totals (id, counts) VALUES (1, '{}')")
    op.create_table(
        "telemetry_metric_samples",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("sampled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lag", sa.BigInteger()),
        sa.Column("counts", sa.JSON(), nullable=False),
        sa.Column("timings", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_telemetry_samples_sampled", "telemetry_metric_samples", ["sampled_at"]
    )
    op.create_table(
        "telemetry_reported_dead_letters",
        sa.Column("topic", sa.String(200), primary_key=True),
        sa.Column("partition", sa.Integer(), primary_key=True),
        sa.Column("offset", sa.BigInteger(), primary_key=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("event_id", sa.Uuid()),
    )
    op.create_index(
        "ix_telemetry_reported_dlq_rejected",
        "telemetry_reported_dead_letters",
        ["rejected_at"],
    )


def downgrade():
    raise RuntimeError(
        "Downgrade would discard live telemetry cursors and diagnostics."
    )
