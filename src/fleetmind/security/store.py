"""Server-side token and account operations."""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from hashlib import sha256
from secrets import compare_digest, token_urlsafe
from threading import BoundedSemaphore, Lock
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import SQLAlchemyError

from fleetmind.db.database import SessionLocal
from fleetmind.security.contracts import CurrentUser, Role
from fleetmind.security.models import (
    AuditEvent,
    AuthSession,
    ServiceCredential,
    UserAccount,
)

HASHER = PasswordHasher(time_cost=2, memory_cost=19_456, parallelism=1)
HASH_SLOTS = BoundedSemaphore(4)
ACCOUNT_LOCK = Lock()
LOGIN_FAILURE = "Invalid username or password."


class SecurityError(ValueError):
    def __init__(self, status, detail):
        self.status = status
        super().__init__(detail)


def now():
    return datetime.now(UTC)


def as_utc(value):
    return value.replace(tzinfo=value.tzinfo or UTC)


def digest(token):
    return sha256(token.encode("utf-8")).hexdigest()


def csrf_value(token):
    return digest("fleetmind-csrf-v1:" + token)


def valid_csrf(token, supplied):
    return (
        supplied is not None
        and len(supplied) == 64
        and supplied.isascii()
        and compare_digest(csrf_value(token), supplied)
    )


@contextmanager
def password_slot():
    if not HASH_SLOTS.acquire(blocking=False):
        raise SecurityError(429, "Password verification is busy. Retry shortly.")
    try:
        yield
    finally:
        HASH_SLOTS.release()


@lru_cache(maxsize=1)
def dummy_hash():
    return HASHER.hash(token_urlsafe(32))


def verify_password(encoded, password):
    try:
        return HASHER.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def audit(db, kind, actor=None, target=None):
    db.add(AuditEvent(kind=kind, actor_id=actor, target_id=target))


@contextmanager
def account_guard(db):
    # Production workers serialize role and activation changes in PostgreSQL.
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(117314)"))
        yield
    else:
        with ACCOUNT_LOCK:
            yield


def administrator(db, user_id):
    user = db.get(UserAccount, user_id)
    if user is None or not user.active or user.role != "administrator":
        raise SecurityError(403, "Administrator access required.")
    return user


@dataclass(frozen=True)
class Principal:
    id: UUID
    role: Role | None
    expires_at: datetime
    username: str | None = None
    session_id: UUID | None = None

    @property
    def is_service(self):
        return self.session_id is None

    def user(self):
        return CurrentUser(
            id=self.id,
            username=self.username,
            role=self.role,
            expires_at=self.expires_at,
        )


class SecurityStore:
    def __init__(self, factory=SessionLocal):
        self.factory = factory

    def record(self, kind, actor=None, target=None):
        try:
            with self.factory.begin() as db:
                audit(db, kind, actor, target)
        except SQLAlchemyError:
            # Denied requests stay denied when audit storage is unavailable.
            return

    def authenticate(self, token, *, service=False):
        if not token or len(token) != 43 or not token.isascii():
            return None
        hashed = digest(token)
        with self.factory() as db:
            if service:
                credential = db.scalar(
                    select(ServiceCredential).where(
                        ServiceCredential.token_hash == hashed,
                        ServiceCredential.revoked_at.is_(None),
                        ServiceCredential.expires_at > now(),
                    )
                )
                return (
                    Principal(credential.id, None, as_utc(credential.expires_at))
                    if credential
                    else None
                )
            found = db.execute(
                select(AuthSession, UserAccount)
                .join(
                    UserAccount,
                    AuthSession.user_id == UserAccount.id,
                )
                .where(
                    AuthSession.token_hash == hashed,
                    AuthSession.revoked_at.is_(None),
                    AuthSession.expires_at > now(),
                    UserAccount.active.is_(True),
                )
            ).one_or_none()
            if found is None:
                return None
            session, user = found
            return self._principal(session, user)

    @staticmethod
    def _principal(session, user):
        return Principal(
            user.id, user.role, as_utc(session.expires_at), user.username, session.id
        )

    @staticmethod
    def _issue(db, user, seconds):
        issued = now()
        # Keep at most eight active sessions per account.
        oldest = (
            select(AuthSession.id)
            .where(
                AuthSession.user_id == user.id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > issued,
            )
            .order_by(AuthSession.created_at.desc(), AuthSession.id)
            .offset(7)
        )
        db.execute(
            update(AuthSession)
            .where(AuthSession.id.in_(oldest))
            .values(revoked_at=issued)
        )
        token = token_urlsafe(32)
        session = AuthSession(
            user_id=user.id,
            token_hash=digest(token),
            created_at=issued,
            expires_at=issued + timedelta(seconds=seconds),
        )
        db.add(session)
        db.flush()
        return token, SecurityStore._principal(session, user)

    def login(self, username, password, seconds, previous=None):
        username = username.casefold()
        with self.factory() as db:
            row = db.execute(
                select(UserAccount.id, UserAccount.password_hash).where(
                    UserAccount.username == username,
                )
            ).one_or_none()
        with password_slot():
            valid = verify_password(
                row.password_hash if row else dummy_hash(), password
            )
            refreshed_hash = (
                HASHER.hash(password)
                if row and valid and HASHER.check_needs_rehash(row.password_hash)
                else None
            )
        if row and valid:
            with self.factory.begin() as db:
                user = db.get(UserAccount, row.id, with_for_update=True)
                if user and user.active and user.password_hash == row.password_hash:
                    if previous and len(previous) == 43 and previous.isascii():
                        db.execute(
                            update(AuthSession)
                            .where(
                                AuthSession.token_hash == digest(previous),
                                AuthSession.user_id == user.id,
                                AuthSession.revoked_at.is_(None),
                            )
                            .values(revoked_at=now())
                        )
                    if refreshed_hash:
                        user.password_hash = refreshed_hash
                    token, principal = self._issue(db, user, seconds)
                    audit(db, "login_succeeded", user.id, principal.session_id)
                    return token, principal
        self.record("login_failed")
        raise SecurityError(401, LOGIN_FAILURE)

    def revoke(self, principal, session_id, kind="session_revoked"):
        with self.factory.begin() as db:
            updated = db.execute(
                update(AuthSession)
                .where(
                    AuthSession.id == session_id,
                    AuthSession.user_id == principal.id,
                    AuthSession.revoked_at.is_(None),
                )
                .values(revoked_at=now())
                .returning(AuthSession.id)
            ).scalar_one_or_none()
            if updated is None:
                raise SecurityError(404, "Session not found.")
            audit(db, kind, principal.id, session_id)

    def change_password(self, principal, current, replacement, seconds):
        with self.factory() as db:
            current_hash = db.scalar(
                select(UserAccount.password_hash).where(
                    UserAccount.id == principal.id,
                )
            )
        with password_slot():
            if not current_hash or not verify_password(current_hash, current):
                self.record("password_change_failed", principal.id)
                raise SecurityError(400, "Current password is incorrect.")
            if current == replacement:
                raise SecurityError(422, "Choose a different password.")
            replacement_hash = HASHER.hash(replacement)
        with self.factory.begin() as db:
            user = db.get(UserAccount, principal.id, with_for_update=True)
            session = db.get(AuthSession, principal.session_id, with_for_update=True)
            if (
                not user
                or not user.active
                or user.password_hash != current_hash
                or not session
                or session.revoked_at is not None
                or as_utc(session.expires_at) <= now()
            ):
                raise SecurityError(401, "Sign in again.")
            user.password_hash = replacement_hash
            user.updated_at = now()
            self.revoke_user_sessions(db, user.id)
            token, result = self._issue(db, user, seconds)
            audit(db, "password_changed", user.id, user.id)
            return token, result

    @staticmethod
    def revoke_user_sessions(db, user_id):
        db.execute(
            update(AuthSession)
            .where(
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=now())
        )

    def create_user(self, username, password, role, *, actor=None):
        with password_slot():
            password_hash = HASHER.hash(password)
        with self.factory.begin() as db, account_guard(db):
            if actor is None:
                if (
                    role != "administrator"
                    or db.scalar(select(UserAccount.id).limit(1)) is not None
                ):
                    raise SecurityError(
                        409, "Initial setup requires an empty user registry."
                    )
            else:
                administrator(db, actor)
            if db.scalar(
                select(UserAccount.id).where(UserAccount.username == username)
            ):
                raise SecurityError(409, "Username is already in use.")
            user = UserAccount(
                username=username, password_hash=password_hash, role=role, active=True
            )
            db.add(user)
            db.flush()
            audit(db, "user_created", actor, user.id)
            return user

    def update_user(self, target, changes, actor):
        with self.factory.begin() as db, account_guard(db):
            administrator(db, actor)
            user = db.get(UserAccount, target, with_for_update=True)
            if user is None:
                raise SecurityError(404, "User not found.")
            active, role = (
                changes.get("active", user.active),
                changes.get("role", user.role),
            )
            if (
                user.active
                and user.role == "administrator"
                and (not active or role != user.role)
            ):
                other = db.scalar(
                    select(func.count())
                    .select_from(UserAccount)
                    .where(
                        UserAccount.active.is_(True),
                        UserAccount.role == "administrator",
                        UserAccount.id != user.id,
                    )
                )
                if not other:
                    raise SecurityError(409, "Keep at least one active administrator.")
            if user.role != role:
                audit(db, "user_role_changed", actor, target)
            if user.active != active:
                audit(
                    db,
                    "user_activated" if active else "user_deactivated",
                    actor,
                    target,
                )
            if (user.active, user.role) != (active, role):
                user.active, user.role, user.updated_at = active, role, now()
                self.revoke_user_sessions(db, target)
            return user

    def new_service(self, name, days, creator):
        token = token_urlsafe(32)
        with self.factory.begin() as db, account_guard(db):
            administrator(db, creator)
            if db.scalar(
                select(ServiceCredential.id).where(ServiceCredential.name == name)
            ):
                raise SecurityError(409, "Service name is already in use.")
            issued = now()
            credential = ServiceCredential(
                name=name,
                created_by=creator,
                token_hash=digest(token),
                created_at=issued,
                expires_at=issued + timedelta(days=days),
            )
            db.add(credential)
            db.flush()
            audit(db, "service_credential_created", creator, credential.id)
            return token, credential.id

    def revoke_service(self, credential_id, actor):
        with self.factory.begin() as db, account_guard(db):
            administrator(db, actor)
            row = db.get(ServiceCredential, credential_id, with_for_update=True)
            if row is None:
                raise SecurityError(404, "Service credential not found.")
            if row.revoked_at is None:
                row.revoked_at = now()
                audit(db, "service_credential_revoked", actor, row.id)
