"""SSE delivery of observable progress and committed answers."""

import asyncio
import logging

import anyio
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from fleetmind.copilot.conversation_schemas import StreamEvent
from fleetmind.copilot.orchestration import Orchestrator
from fleetmind.copilot.schemas import ChatRequest
from fleetmind.security.protect import stream_allowed

logger = logging.getLogger(__name__)


def frame(event: StreamEvent) -> bytes:
    data = event.model_dump_json(exclude_none=True)
    return f"event: {event.type}\ndata: {data}\n\n".encode()


async def conversation_stream(
    http_request, store, identifier, reservation, provider, context, settings, executor
):
    request_id = reservation.user.request_id
    producer = None
    terminal = False
    cleanup_state = "cancelled"
    queue: asyncio.Queue[StreamEvent] = asyncio.Queue()

    def emit(kind, **details):
        queue.put_nowait(StreamEvent(type=kind, request_id=request_id, **details))

    def event(kind, **details):
        return frame(StreamEvent(type=kind, request_id=request_id, **details))

    try:
        if not await stream_allowed(http_request, force=True):
            yield event("session_expired", detail="Sign in again to use Copilot.")
            return
        yield event("started", user=reservation.user)
        message = reservation.replay
        if message is None:
            question = ChatRequest(
                question=reservation.user.content,
                asset_id=reservation.user.asset_id,
                context=reservation.context,
            )
            producer = asyncio.create_task(
                Orchestrator(provider, executor, settings, on_event=emit).chat(
                    question, context
                )
            )
            while not producer.done() or not queue.empty():
                if not await stream_allowed(http_request):
                    yield event(
                        "session_expired", detail="Sign in again to use Copilot."
                    )
                    return
                if await http_request.is_disconnected():
                    return
                try:
                    progress = await asyncio.wait_for(queue.get(), 0.5)
                except TimeoutError:
                    if await http_request.is_disconnected():
                        return
                    state = await run_in_threadpool(store.state, identifier, request_id)
                    if state != "pending":
                        if state != "completed":
                            yield event("cancelled", detail="The request was stopped.")
                        terminal = True
                        return
                    if not producer.done():
                        yield b": waiting\n\n"
                else:
                    yield frame(progress)
            if await http_request.is_disconnected():
                return
            answer = await producer
            if not await stream_allowed(http_request, force=True):
                yield event("session_expired", detail="Sign in again to use Copilot.")
                return
            message = await run_in_threadpool(
                store.finish,
                identifier,
                request_id,
                answer,
                settings.provider,
                settings.model or None,
            )
            if message is None:
                terminal = True
                yield event(
                    "cancelled", detail="The request was stopped before saving."
                )
                return
        terminal = True
        if message.response_status == "clarification_required":
            yield event("clarification")
        if message.response_status == "unavailable":
            issues = message.response.diagnostics.issues if message.response else []
            if "request_deadline" in issues or "provider_timeout" in issues:
                detail = "The request reached its time limit. Try a narrower question."
            elif "provider_rate_limited" in issues:
                detail = "The provider reached its rate limit. Wait before retrying."
            else:
                detail = "The provider could not complete the request."
            yield event("error", detail=detail)
        yield event("final", message=message)
        yield event("completed")
    except (SQLAlchemyError, ValueError, RuntimeError) as exc:
        cleanup_state = "failed"
        logger.warning("Conversation stream failed (%s)", type(exc).__name__)
        yield event(
            "error", detail="The request could not be completed. Retry the question."
        )
    finally:
        if producer is not None and not producer.done():
            producer.cancel()
        with anyio.CancelScope(shield=True):
            if producer is not None:
                await asyncio.gather(producer, return_exceptions=True)
            if not terminal and reservation.replay is None:
                try:
                    await run_in_threadpool(
                        store.terminate, identifier, request_id, cleanup_state
                    )
                except SQLAlchemyError:
                    logger.warning("Conversation lease cleanup failed")
