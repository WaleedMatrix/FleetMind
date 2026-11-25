"""Non-streaming Copilot routes for trusted local development."""

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from fleetmind.copilot.execution import ToolExecutor
from fleetmind.copilot.orchestration import Orchestrator
from fleetmind.copilot.providers import make_provider
from fleetmind.copilot.schemas import ChatRequest, ChatResponse, Diagnostics
from fleetmind.copilot.settings import MissingCredentials, Settings
from fleetmind.copilot.tools import ToolContext
from fleetmind.copilot.validation import response
from fleetmind.knowledge.embeddings import get_embedder

router = APIRouter(prefix="/api/v1/copilot", tags=["copilot"])


class CopilotStatus(BaseModel):
    configured: bool
    provider: str
    model: str | None = None
    detail: str
    reason: str
    embedding_state: str


@router.get("/status", response_model=CopilotStatus)
def copilot_status():
    embedding_state = get_embedder().initialization_state
    try:
        settings = Settings.from_environment()
    except MissingCredentials:
        return CopilotStatus(
            configured=False,
            provider="unavailable",
            reason="credentials_missing",
            embedding_state=embedding_state,
            detail="Hosted provider credentials are missing.",
        )
    except ValueError:
        return CopilotStatus(
            configured=False,
            provider="unavailable",
            detail="Copilot provider configuration is invalid.",
            reason="invalid_configuration",
            embedding_state=embedding_state,
        )
    enabled = settings.provider != "disabled"
    return CopilotStatus(
        configured=enabled,
        provider=settings.provider,
        model=settings.model or None,
        reason="configured" if enabled else "disabled",
        embedding_state=embedding_state,
        detail="Provider configured; connectivity is checked on demand."
        if enabled
        else "Copilot is disabled.",
    )


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={503: {"model": ChatResponse}, 504: {"model": ChatResponse}},
)
async def copilot_chat(payload: ChatRequest, request: Request, http_response: Response):
    try:
        settings = Settings.from_environment()
    except ValueError:
        settings = Settings()
    if settings.provider == "disabled":
        http_response.status_code = 503
        return response("unavailable", Diagnostics(issues=["provider_not_configured"]))
    provider = make_provider(settings)
    scope = ToolContext(
        question=payload.question,
        asset_id=payload.asset_id,
        model_version=request.app.state.model_version,
        explainer=request.app.state.explainer,
        intelligence=request.app.state.model_intelligence,
    )
    result = await Orchestrator(provider, ToolExecutor(), settings).chat(payload, scope)
    if result.status == "unavailable":
        issues = set(result.diagnostics.issues)
        http_response.status_code = (
            504 if issues & {"request_deadline", "provider_timeout"} else 503
        )
    return result
