"""Accounts, sessions, prediction credentials, and structured audit events."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from fleetmind.db.database import Base

ROLE_CHECK = "role IN ('administrator', 'engineer', 'viewer')"


class UserAccount(Base):
    __tablename__ = "auth_users"
    __table_args__ = (
        CheckConstraint(ROLE_CHECK, name="ck_auth_user_role"),
        Index("ix_auth_user_active_role", "active", "role"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(16))
    active: Mapped[bool] = mapped_column(server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        Index("ix_auth_session_user_expiry", "user_id", "expires_at"),
        Index("ix_auth_session_expiry", "expires_at"),
        CheckConstraint("expires_at > created_at", name="ck_auth_session_expiry"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("auth_users.id", name="fk_auth_session_user", ondelete="CASCADE"),
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ServiceCredential(Base):
    __tablename__ = "auth_service_credentials"
    __table_args__ = (
        Index("ix_auth_service_expiry", "expires_at"),
        CheckConstraint("expires_at > created_at", name="ck_auth_service_expiry"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("auth_users.id", name="fk_auth_service_creator"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base):
    __tablename__ = "auth_audit_events"
    __table_args__ = (Index("ix_auth_audit_created", "created_at", "id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    kind: Mapped[str] = mapped_column(String(48))
    actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth_users.id", name="fk_auth_audit_actor", ondelete="SET NULL"),
    )
    target_id: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
