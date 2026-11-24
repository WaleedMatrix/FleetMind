"""Atomic conversation operations. Each call owns its database transaction."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select

from fleetmind.copilot.conversation_models import Conversation, ConversationMessage
from fleetmind.copilot.conversation_schemas import (
    ConversationInfo,
    ConversationPage,
    MessageInfo,
    MessagePage,
    MessageState,
)
from fleetmind.copilot.schemas import ChatContext, ChatResponse
from fleetmind.db.database import SessionLocal
from fleetmind.db.models import Asset, PredictionHistory

NEW_TITLE = "New conversation"


class ConversationError(ValueError):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status


@dataclass
class Reservation:
    user: MessageInfo
    context: list[ChatContext]
    replay: MessageInfo | None = None


def validate_context(db, asset_id, prediction_id):
    if asset_id is not None and db.get(Asset, asset_id) is None:
        raise ConversationError(422, "The selected asset does not exist.")
    if prediction_id is not None:
        record = db.get(PredictionHistory, prediction_id)
        if record is None:
            raise ConversationError(422, "The selected prediction does not exist.")
        if asset_id is not None and record.asset_id != asset_id:
            raise ConversationError(
                422, "The prediction does not belong to the selected asset."
            )


class ConversationStore:
    def __init__(self, factory=SessionLocal):
        self.factory = factory

    @staticmethod
    def _get(db, identifier: UUID, *, lock: bool = False):
        row = db.get(Conversation, identifier, with_for_update=lock)
        if row is None:
            raise ConversationError(404, "Conversation not found.")
        return row

    @staticmethod
    def _by_request(db, identifier, request_id, role="user"):
        return db.scalar(
            select(ConversationMessage).where(
                ConversationMessage.conversation_id == identifier,
                ConversationMessage.request_id == request_id,
                ConversationMessage.role == role,
            )
        )

    @staticmethod
    def _active(db, identifier):
        active = db.scalar(
            select(ConversationMessage).where(
                ConversationMessage.conversation_id == identifier,
                ConversationMessage.role == "user",
                ConversationMessage.state == "pending",
            )
        )
        if active and active.lease_until:
            now = datetime.now(UTC)
            if (
                active.lease_until.replace(tzinfo=active.lease_until.tzinfo or UTC)
                <= now
            ):
                active.state = "cancelled"
                active.lease_until = None
                db.flush()
                return None
        return active

    def create(self, payload):
        with self.factory.begin() as db:
            validate_context(db, payload.asset_id, payload.prediction_id)
            row = Conversation(**payload.model_dump())
            db.add(row)
            db.flush()
            return ConversationInfo.model_validate(row)

    def list(self, q, archived, limit, offset):
        with self.factory() as db:
            query = select(Conversation).where(Conversation.archived == archived)
            if q:
                matches_message = (
                    select(ConversationMessage.id)
                    .where(
                        ConversationMessage.conversation_id == Conversation.id,
                        ConversationMessage.content.icontains(q, autoescape=True),
                    )
                    .exists()
                )
                query = query.where(
                    or_(
                        Conversation.title.icontains(q, autoescape=True),
                        matches_message,
                    )
                )
            rows = list(
                db.scalars(
                    query.order_by(
                        Conversation.updated_at.desc(), Conversation.id.desc()
                    )
                    .limit(limit + 1)
                    .offset(offset)
                )
            )
            return ConversationPage(
                items=[ConversationInfo.model_validate(row) for row in rows[:limit]],
                next_offset=offset + limit if len(rows) > limit else None,
            )

    def get(self, identifier):
        with self.factory() as db:
            return ConversationInfo.model_validate(self._get(db, identifier))

    def update(self, identifier, payload):
        with self.factory.begin() as db:
            row = self._get(db, identifier, lock=True)
            if self._active(db, identifier):
                raise ConversationError(409, "Stop the active request before editing.")
            changes = payload.model_dump(exclude_unset=True)
            validate_context(
                db,
                changes.get("asset_id", row.asset_id),
                changes.get("prediction_id", row.prediction_id),
            )
            for field, value in changes.items():
                setattr(row, field, value)
            row.updated_at = datetime.now(UTC)
            return ConversationInfo.model_validate(row)

    def delete(self, identifier, confirmation):
        if identifier != confirmation:
            raise ConversationError(400, "Confirm deletion with the conversation ID.")
        with self.factory.begin() as db:
            row = self._get(db, identifier, lock=True)
            if self._active(db, identifier):
                raise ConversationError(409, "Stop the active request before deleting.")
            db.delete(row)

    def messages(self, identifier, limit, before_id):
        with self.factory() as db:
            self._get(db, identifier)
            query = select(ConversationMessage).where(
                ConversationMessage.conversation_id == identifier
            )
            if before_id is not None:
                query = query.where(ConversationMessage.id < before_id)
            rows = list(
                db.scalars(
                    query.order_by(ConversationMessage.id.desc()).limit(limit + 1)
                )
            )
            return MessagePage(
                items=[
                    MessageInfo.model_validate(row) for row in reversed(rows[:limit])
                ],
                next_before_id=rows[limit - 1].id if len(rows) > limit else None,
            )

    def reserve(self, identifier, payload, request_timeout):
        with self.factory.begin() as db:
            row = self._get(db, identifier, lock=True)
            active = self._active(db, identifier)
            prior = self._by_request(db, identifier, payload.request_id)
            if prior:
                if prior.content != payload.question:
                    raise ConversationError(
                        409, "This request ID was used for another question."
                    )
                assistant = self._by_request(
                    db, identifier, payload.request_id, "assistant"
                )
                if assistant:
                    return Reservation(
                        MessageInfo.model_validate(prior),
                        [],
                        MessageInfo.model_validate(assistant),
                    )
                raise ConversationError(
                    409,
                    f"This request is {prior.state}. Use a new request ID to retry.",
                )
            if active or row.archived:
                raise ConversationError(
                    409,
                    "Restore the conversation before sending."
                    if row.archived
                    else "Another request is already running in this conversation.",
                )
            validate_context(db, row.asset_id, row.prediction_id)
            history = list(
                db.scalars(
                    select(ConversationMessage)
                    .where(
                        ConversationMessage.conversation_id == identifier,
                        ConversationMessage.state == "completed",
                        ConversationMessage.asset_id == row.asset_id,
                        ConversationMessage.prediction_id == row.prediction_id,
                        or_(
                            ConversationMessage.role == "user",
                            ConversationMessage.response_status != "unavailable",
                        ),
                    )
                    .order_by(ConversationMessage.id.desc())
                    .limit(4)
                )
            )
            previous = [
                ChatContext(role=message.role, content=message.content[:600].strip())
                for message in reversed(history)
            ]
            now = datetime.now(UTC)
            user = ConversationMessage(
                conversation_id=identifier,
                request_id=payload.request_id,
                role="user",
                state="pending",
                content=payload.question,
                asset_id=row.asset_id,
                prediction_id=row.prediction_id,
                lease_until=now + timedelta(seconds=request_timeout + 10),
            )
            if row.title == NEW_TITLE:
                row.title = " ".join(payload.question.split())[:72].strip()
            row.updated_at = now
            db.add(user)
            db.flush()
            return Reservation(MessageInfo.model_validate(user), previous)

    def state(self, identifier, request_id) -> MessageState | None:
        with self.factory() as db:
            row = self._by_request(db, identifier, request_id)
            return row.state if row else None

    def terminate(self, identifier, request_id, state: MessageState = "cancelled"):
        with self.factory.begin() as db:
            row = db.get(Conversation, identifier, with_for_update=True)
            if row is None:
                return None
            user = self._by_request(db, identifier, request_id)
            if user and user.state == "pending":
                user.state = state
                user.lease_until = None
                row.updated_at = datetime.now(UTC)
            return user.state if user else None

    def finish(self, identifier, request_id, answer: ChatResponse, provider, model):
        with self.factory.begin() as db:
            row = db.get(Conversation, identifier, with_for_update=True)
            if row is None:
                return None
            self._active(db, identifier)
            user = self._by_request(db, identifier, request_id)
            if user is None or user.state != "pending":
                return None
            user.state = "completed"
            user.lease_until = None
            row.updated_at = datetime.now(UTC)
            assistant = ConversationMessage(
                conversation_id=identifier,
                request_id=request_id,
                role="assistant",
                state="completed",
                content=answer.answer,
                asset_id=user.asset_id,
                prediction_id=user.prediction_id,
                response_status=answer.status,
                response=answer.model_dump(mode="json"),
                provider=provider,
                model=model,
            )
            db.add(assistant)
            db.flush()
            return MessageInfo.model_validate(assistant)
