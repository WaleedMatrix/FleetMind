"""Add security storage and nullable legacy conversation ownership."""

import sqlalchemy as sa
from alembic import op

revision = "0007_application_security"
down_revision = "0006_telemetry_live_monitoring"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "auth_users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column(
            "active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('administrator', 'engineer', 'viewer')", name="ck_auth_user_role"
        ),
    )
    op.create_index("ix_auth_user_active_role", "auth_users", ["active", "role"])
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth_users.id"],
            name="fk_auth_session_user",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_auth_session_expiry"),
    )
    op.create_index(
        "ix_auth_session_user_expiry", "auth_sessions", ["user_id", "expires_at"]
    )
    op.create_index("ix_auth_session_expiry", "auth_sessions", ["expires_at"])
    op.create_table(
        "auth_service_credentials",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["created_by"], ["auth_users.id"], name="fk_auth_service_creator"
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_auth_service_expiry"),
    )
    op.create_index(
        "ix_auth_service_expiry", "auth_service_credentials", ["expires_at"]
    )
    op.create_table(
        "auth_audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(48), nullable=False),
        sa.Column("actor_id", sa.Uuid()),
        sa.Column("target_id", sa.Uuid()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["auth_users.id"],
            name="fk_auth_audit_actor",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_auth_audit_created", "auth_audit_events", ["created_at", "id"])
    op.add_column("copilot_conversations", sa.Column("owner_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_copilot_conversation_owner",
        "copilot_conversations",
        "auth_users",
        ["owner_id"],
        ["id"],
    )
    op.create_index(
        "ix_copilot_conversation_owner_archive",
        "copilot_conversations",
        ["owner_id", "archived", "updated_at", "id"],
    )


def downgrade():
    raise RuntimeError(
        "Downgrade would remove authentication and conversation ownership."
    )
