"""Browser session endpoints and audited administration."""

from contextlib import contextmanager
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from fleetmind.copilot.conversation_models import Conversation
from fleetmind.security.contracts import (
    AccountCreate,
    AccountInfo,
    AccountUpdate,
    AuditInfo,
    CurrentUser,
    Login,
    OrphanAction,
    OrphanInfo,
    PasswordChange,
    ServiceInfo,
    SessionInfo,
)
from fleetmind.security.models import (
    AuditEvent,
    AuthSession,
    ServiceCredential,
    UserAccount,
)
from fleetmind.security.store import (
    SecurityError,
    account_guard,
    administrator,
    as_utc,
    audit,
    csrf_value,
    now,
)

router = APIRouter(prefix="/api/v1")
PageSize = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=100_000)]


@contextmanager
def security_errors():
    try:
        yield
    except SecurityError as exc:
        headers = {"Retry-After": "5"} if exc.status == 429 else None
        raise HTTPException(exc.status, str(exc), headers=headers) from None
    except SQLAlchemyError:
        raise HTTPException(503, "Security storage is unavailable.") from None


def write_session(response, settings, token, principal):
    options = dict(
        secure=not settings.insecure_local_http,
        samesite="lax",
        path="/",
        max_age=settings.session_seconds,
        expires=principal.expires_at,
    )
    response.set_cookie(settings.cookie, token, httponly=True, **options)
    response.set_cookie(settings.csrf_cookie, csrf_value(token), **options)


def clear_session(response, settings):
    options = dict(secure=not settings.insecure_local_http, samesite="lax", path="/")
    response.delete_cookie(settings.cookie, httponly=True, **options)
    response.delete_cookie(settings.csrf_cookie, **options)


@router.post("/auth/login", response_model=CurrentUser)
def login(payload: Login, request: Request, response: Response):
    state = request.state
    username = payload.username.casefold()
    if retry := state.auth_limits.take(("login_account", username), 5):
        return JSONResponse(
            {"detail": "Too many sign-in attempts. Retry shortly."},
            status_code=429,
            headers={"Retry-After": str(retry)},
        )
    settings = state.auth_settings
    with security_errors():
        token, principal = state.auth_store.login(
            username,
            payload.password.get_secret_value(),
            settings.session_seconds,
            request.cookies.get(settings.cookie),
        )
    write_session(response, settings, token, principal)
    return principal.user()


@router.get("/auth/me", response_model=CurrentUser)
def current_user(request: Request):
    return request.state.principal.user()


@router.post("/auth/logout", status_code=204)
def logout(request: Request):
    state = request.state
    with security_errors():
        state.auth_store.revoke(state.principal, state.principal.session_id, "logout")
    response = Response(status_code=204)
    clear_session(response, state.auth_settings)
    return response


@router.post("/auth/password", response_model=CurrentUser)
def change_password(payload: PasswordChange, request: Request, response: Response):
    state = request.state
    with security_errors():
        token, principal = state.auth_store.change_password(
            state.principal,
            payload.current_password.get_secret_value(),
            payload.new_password.get_secret_value(),
            state.auth_settings.session_seconds,
        )
    write_session(response, state.auth_settings, token, principal)
    return principal.user()


@router.get("/auth/sessions", response_model=list[SessionInfo])
def sessions(request: Request):
    state = request.state
    with security_errors(), state.auth_store.factory() as db:
        rows = db.scalars(
            select(AuthSession)
            .where(
                AuthSession.user_id == state.principal.id,
                AuthSession.expires_at > now(),
                AuthSession.revoked_at.is_(None),
            )
            .order_by(AuthSession.created_at.desc())
        ).all()
        return [
            SessionInfo(
                id=row.id,
                created_at=as_utc(row.created_at),
                expires_at=as_utc(row.expires_at),
                current=row.id == state.principal.session_id,
            )
            for row in rows
        ]


@router.delete("/auth/sessions/{session_id}", status_code=204)
def revoke_session(session_id: UUID, request: Request):
    state = request.state
    with security_errors():
        state.auth_store.revoke(state.principal, session_id)
    response = Response(status_code=204)
    if session_id == state.principal.session_id:
        clear_session(response, state.auth_settings)
    return response


@router.get("/admin/users", response_model=list[AccountInfo])
def list_users(request: Request, limit: PageSize = 50, offset: Offset = 0):
    with security_errors(), request.state.auth_store.factory() as db:
        return [
            AccountInfo.model_validate(row)
            for row in db.scalars(
                select(UserAccount)
                .order_by(UserAccount.username)
                .limit(limit)
                .offset(offset)
            )
        ]


@router.post("/admin/users", response_model=AccountInfo, status_code=201)
def create_user(payload: AccountCreate, request: Request):
    with security_errors():
        return request.state.auth_store.create_user(
            payload.username,
            payload.password.get_secret_value(),
            payload.role,
            actor=request.state.principal.id,
        )


@router.patch("/admin/users/{user_id}", response_model=AccountInfo)
def update_user(user_id: UUID, payload: AccountUpdate, request: Request):
    with security_errors():
        return request.state.auth_store.update_user(
            user_id,
            payload.model_dump(exclude_unset=True),
            request.state.principal.id,
        )


@router.get("/admin/audit", response_model=list[AuditInfo])
def list_audit(request: Request, limit: PageSize = 50, offset: Offset = 0):
    with security_errors(), request.state.auth_store.factory() as db:
        return [
            AuditInfo.model_validate(row)
            for row in db.scalars(
                select(AuditEvent)
                .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ]


@router.get("/admin/service-credentials", response_model=list[ServiceInfo])
def list_credentials(request: Request, limit: PageSize = 50, offset: Offset = 0):
    with security_errors(), request.state.auth_store.factory() as db:
        return [
            ServiceInfo.model_validate(row)
            for row in db.scalars(
                select(ServiceCredential)
                .order_by(ServiceCredential.name)
                .limit(limit)
                .offset(offset)
            )
        ]


@router.delete("/admin/service-credentials/{credential_id}", status_code=204)
def revoke_credential(credential_id: UUID, request: Request):
    with security_errors():
        request.state.auth_store.revoke_service(
            credential_id, request.state.principal.id
        )
    return Response(status_code=204)


@router.get("/admin/orphan-conversations", response_model=list[OrphanInfo])
def list_orphans(request: Request, limit: PageSize = 50, offset: Offset = 0):
    with security_errors(), request.state.auth_store.factory() as db:
        return [
            OrphanInfo.model_validate(row)
            for row in db.scalars(
                select(Conversation)
                .where(Conversation.owner_id.is_(None))
                .order_by(Conversation.created_at.desc(), Conversation.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ]


@router.patch(
    "/admin/orphan-conversations/{conversation_id}", response_model=OrphanInfo
)
def handle_orphan(conversation_id: UUID, payload: OrphanAction, request: Request):
    state = request.state
    with security_errors(), state.auth_store.factory.begin() as db, account_guard(db):
        administrator(db, state.principal.id)
        row = db.scalar(
            select(Conversation)
            .where(
                Conversation.id == conversation_id,
                Conversation.owner_id.is_(None),
            )
            .with_for_update()
        )
        if row is None:
            raise SecurityError(404, "Legacy conversation not found.")
        if payload.action == "adopt":
            owner = db.get(UserAccount, payload.owner_id)
            if owner is None or not owner.active or owner.role == "viewer":
                raise SecurityError(422, "Choose an active engineer or administrator.")
            row.owner_id = owner.id
            audit(db, "conversation_adopted", state.principal.id, row.id)
        else:
            row.archived = True
            audit(db, "conversation_archived", state.principal.id, row.id)
        row.updated_at = now()
        return OrphanInfo.model_validate(row)
