"""Trusted-local conversation persistence and streaming routes."""

from contextlib import contextmanager
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from fleetmind.copilot.conversation_schemas import (
    ConversationCreate,
    ConversationInfo,
    ConversationPage,
    ConversationUpdate,
    MessageInput,
    MessagePage,
    RequestState,
)
from fleetmind.copilot.conversations import ConversationError, ConversationStore
from fleetmind.copilot.execution import ToolExecutor
from fleetmind.copilot.providers import make_provider
from fleetmind.copilot.settings import Settings
from fleetmind.copilot.streaming import conversation_stream
from fleetmind.copilot.tools import ToolContext

router = APIRouter(
    prefix="/api/v1/copilot/conversations", tags=["copilot conversations"]
)


def conversation_store():
    return ConversationStore()


Store = Annotated[ConversationStore, Depends(conversation_store)]
Limit = Annotated[int, Query(ge=1, le=50)]
Offset = Annotated[int, Query(ge=0, le=100_000)]


@contextmanager
def store_errors():
    try:
        yield
    except ConversationError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None
    except SQLAlchemyError:
        raise HTTPException(
            status_code=503, detail="Conversation storage is unavailable."
        ) from None


@router.post("", response_model=ConversationInfo, status_code=201)
def create(payload: ConversationCreate, store: Store):
    with store_errors():
        return store.create(payload)


@router.get("", response_model=ConversationPage)
def list_conversations(
    store: Store,
    q: Annotated[str, Query(max_length=120, pattern=r"^[^\x00]*$")] = "",
    archived: bool = False,
    limit: Limit = 20,
    offset: Offset = 0,
):
    with store_errors():
        return store.list(q.strip(), archived, limit, offset)


@router.get("/{conversation_id}", response_model=ConversationInfo)
def inspect_conversation(conversation_id: UUID, store: Store):
    with store_errors():
        return store.get(conversation_id)


@router.patch("/{conversation_id}", response_model=ConversationInfo)
def update(conversation_id: UUID, payload: ConversationUpdate, store: Store):
    with store_errors():
        return store.update(conversation_id, payload)


@router.delete("/{conversation_id}", status_code=204)
def delete(conversation_id: UUID, confirm: Annotated[UUID, Query()], store: Store):
    with store_errors():
        store.delete(conversation_id, confirm)
    return Response(status_code=204)


@router.get("/{conversation_id}/messages", response_model=MessagePage)
def messages(
    conversation_id: UUID,
    store: Store,
    limit: Limit = 25,
    before_id: Annotated[int | None, Query(gt=0, le=2_147_483_647)] = None,
):
    with store_errors():
        return store.messages(conversation_id, limit, before_id)


@router.post(
    "/{conversation_id}/requests/{request_id}/cancel", response_model=RequestState
)
def cancel(conversation_id: UUID, request_id: UUID, store: Store):
    with store_errors():
        state = store.terminate(conversation_id, request_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Conversation request not found.")
    return RequestState(state=state)


@router.post("/{conversation_id}/messages/stream")
async def send(
    conversation_id: UUID, payload: MessageInput, request: Request, store: Store
):
    try:
        settings = Settings.from_environment()
    except ValueError:
        raise HTTPException(
            status_code=503, detail="Copilot provider configuration is unavailable."
        ) from None
    if settings.provider == "disabled":
        raise HTTPException(status_code=503, detail="Copilot is disabled.")
    with store_errors():
        reservation = await run_in_threadpool(
            store.reserve,
            conversation_id,
            payload,
            settings.request_timeout,
        )
    context = ToolContext(
        question=reservation.user.content,
        asset_id=reservation.user.asset_id,
        model_version=request.app.state.model_version,
        explainer=request.app.state.explainer,
        intelligence=request.app.state.model_intelligence,
        prediction_id=reservation.user.prediction_id,
    )
    return StreamingResponse(
        conversation_stream(
            request,
            store,
            conversation_id,
            reservation,
            make_provider(settings),
            context,
            settings,
            ToolExecutor(),
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
