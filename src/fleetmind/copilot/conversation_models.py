"""Persistent conversation context and idempotent message turns."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from fleetmind.db.database import Base

PENDING_USER = "role = 'user' AND state = 'pending'"
MESSAGE_SHAPE = (
    "(role = 'user' AND response IS NULL AND response_status IS NULL "
    "AND state IN ('pending', 'completed', 'cancelled', 'failed')) OR "
    "(role = 'assistant' AND state = 'completed' AND response IS NOT NULL "
    "AND response_status IS NOT NULL "
    "AND response_status IN ('answered', 'clarification_required', "
    "'insufficient_evidence', 'unavailable'))"
)


class Conversation(Base):
    __tablename__ = "copilot_conversations"
    __table_args__ = (
        Index(
            "ix_copilot_conversation_archive_updated", "archived", "updated_at", "id"
        ),
        Index(
            "ix_copilot_conversation_owner_archive",
            "owner_id",
            "archived",
            "updated_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(120))
    owner_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth_users.id", name="fk_copilot_conversation_owner"),
    )
    archived: Mapped[bool] = mapped_column(server_default=text("false"))
    asset_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "assets.asset_id", name="fk_copilot_conversation_asset", ondelete="SET NULL"
        )
    )
    prediction_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "prediction_history.id",
            name="fk_copilot_conversation_prediction",
            ondelete="SET NULL",
        )
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ConversationMessage(Base):
    __tablename__ = "copilot_messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "request_id",
            "role",
            name="uq_copilot_message_request_role",
        ),
        CheckConstraint(MESSAGE_SHAPE, name="ck_copilot_message_shape"),
        Index("ix_copilot_message_conversation_id", "conversation_id", "id"),
        Index(
            "ux_copilot_pending_conversation",
            "conversation_id",
            unique=True,
            postgresql_where=text(PENDING_USER),
            sqlite_where=text(PENDING_USER),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "copilot_conversations.id",
            name="fk_copilot_message_conversation",
            ondelete="CASCADE",
        )
    )
    request_id: Mapped[UUID] = mapped_column(Uuid())
    role: Mapped[str] = mapped_column(String(9))
    state: Mapped[str] = mapped_column(String(12))
    content: Mapped[str] = mapped_column(Text)
    asset_id: Mapped[str | None] = mapped_column(String(64))
    prediction_id: Mapped[int | None] = mapped_column(Integer)
    response_status: Mapped[str | None] = mapped_column(String(24))
    response: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    provider: Mapped[str | None] = mapped_column(String(20))
    model: Mapped[str | None] = mapped_column(String(160))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
