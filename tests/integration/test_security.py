"""Defensive authentication, policy, ownership and revocation regression tests."""

import asyncio
from contextlib import aclosing, contextmanager
from datetime import timedelta
from threading import BoundedSemaphore
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from fleetmind.api import copilot_conversations as routes
from fleetmind.api.main import app
from fleetmind.copilot import streaming
from fleetmind.copilot.conversation_models import Conversation
from fleetmind.copilot.conversation_schemas import ConversationCreate, MessageInput
from fleetmind.copilot.conversations import ConversationStore
from fleetmind.copilot.settings import Settings
from fleetmind.db.database import Base, get_db
from fleetmind.security.models import AuditEvent, AuthSession, UserAccount
from fleetmind.security.protect import StreamSession
from fleetmind.security.settings import SecuritySettings
from fleetmind.security.store import csrf_value, digest, now
from fleetmind.telemetry.live import FeedFilter, committed_stream

AUTH = "/api/v1/auth"
ADMIN = "/api/v1/admin"
CONVERSATIONS = "/api/v1/copilot/conversations"
ORIGIN = "http://testserver"
PASSWORD = "Valid-fixture-password"


@pytest.fixture
def world(install_auth, seed_account, sign_in, monkeypatch):
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    store = install_auth(factory)
    ids = {
        role: seed_account(factory, role + "-test", role)
        for role in (
            "administrator",
            "engineer",
            "viewer",
        )
    }
    ids["other"] = seed_account(factory, "another-engineer")

    def session():
        with factory() as db:
            yield db

    monkeypatch.setitem(app.dependency_overrides, get_db, session)
    monkeypatch.setitem(
        app.dependency_overrides,
        routes.conversation_store,
        lambda: ConversationStore(factory),
    )

    @contextmanager
    def browser(role=None):
        client = TestClient(app)
        try:
            if role:
                name = "another-engineer" if role == "other" else role + "-test"
                assert sign_in(client, name).status_code == 200
            yield client
        finally:
            client.close()

    try:
        with TestClient(app):
            yield store, ids, browser
    finally:
        engine.dispose()


def test_public_routes_and_role_access(world):
    _, _, browser = world
    with (
        browser() as anonymous,
        browser("viewer") as viewer,
        browser("engineer") as engineer,
    ):
        assert anonymous.get("/health").json() == {"status": "ok"}
        for path in (
            "/docs",
            "/api/v1/predictions",
            "/api/v1/assets",
            "/api/v1/model/intelligence",
            "/api/v1/telemetry/stream",
            "/api/v1/copilot/status",
            "/api/v1/knowledge/status",
            ADMIN + "/users",
        ):
            assert anonymous.get(path).status_code == 401
        assert viewer.get("/api/v1/predictions").status_code == 200
        assert viewer.get("/api/v1/assets").status_code == 200
        for path in (
            CONVERSATIONS,
            ADMIN + "/users",
            "/api/v1/telemetry/dead-letters",
            "/api/v1/knowledge/status",
        ):
            assert viewer.get(path).status_code == 403
        assert viewer.post("/api/v1/predict", json={}).status_code == 403
        assert viewer.patch("/api/v1/assets/press", json={}).status_code == 403
        assert engineer.get(ADMIN + "/users").status_code == 403


def test_origin_csrf_rotation_and_password_hash(world, sign_in):
    store, ids, browser = world
    with browser("engineer") as client, browser("engineer") as older:
        token = client.cookies["fleetmind_session"]
        older_token = older.cookies["fleetmind_session"]
        sid = store.authenticate(token).session_id
        with store.factory() as db:
            assert db.get(UserAccount, ids["engineer"]).password_hash.startswith(
                "$argon2id$"
            )
            assert db.get(AuthSession, sid).token_hash == digest(token)
        assert (
            client.post(AUTH + "/logout", headers={"X-FleetMind-CSRF": ""}).status_code
            == 403
        )
        assert (
            client.post(
                AUTH + "/logout", headers={"Origin": "https://untrusted.example"}
            ).status_code
            == 403
        )
        assert TestClient(app).post(AUTH + "/login", json={}).status_code == 403
        response = sign_in(client, "ENGINEER-TEST")
        assert response.status_code == 200
        assert "HttpOnly" in response.headers.get_list("set-cookie")[0]
        assert "SameSite=lax" in response.headers.get_list("set-cookie")[0]
        assert store.authenticate(token) is None
        new_session = client.cookies["fleetmind_session"]
        assert new_session != token and client.cookies["fleetmind_csrf"] == csrf_value(
            new_session
        )
        result = client.post(
            AUTH + "/password",
            json={
                "current_password": PASSWORD,
                "new_password": "Replacement-fixture-password",
            },
        )
        assert result.status_code == 200
        client.headers["X-FleetMind-CSRF"] = client.cookies["fleetmind_csrf"]
        assert store.authenticate(new_session) is None
        assert store.authenticate(older_token) is None
        assert older.get(AUTH + "/me").status_code == 401
        assert client.post(AUTH + "/logout").status_code == 204
        assert client.get(AUTH + "/me").status_code == 401


def test_identical_failures_login_throttling_and_expiration(world, sign_in):
    store, _, browser = world
    with browser() as anonymous, browser("viewer") as viewer:
        first = sign_in(anonymous, "engineer-test", password="Wrong")
        unknown = sign_in(anonymous, "unknown-test", password="Wrong")
        assert first.status_code == unknown.status_code == 401
        assert first.json() == unknown.json()
        for _ in range(4):
            assert (
                sign_in(anonymous, "engineer-test", password="Wrong").status_code == 401
            )
        blocked = sign_in(anonymous, "engineer-test")
        assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) > 0
        current = store.authenticate(viewer.cookies["fleetmind_session"])
        assert current is not None
        old = now() - timedelta(hours=2)
        with store.factory.begin() as db:
            db.execute(
                update(AuthSession)
                .where(AuthSession.id == current.session_id)
                .values(
                    created_at=old,
                    expires_at=old + timedelta(hours=1),
                )
            )
        assert viewer.get(AUTH + "/me").status_code == 401
        with store.factory() as db:
            assert "login_failed" in db.scalars(select(AuditEvent.kind)).all()


def test_prevent_privilege_escalation_and_last_administrator(world):
    _, ids, browser = world
    with browser("administrator") as admin, browser("engineer") as engineer:
        target = ADMIN + "/users/" + str(ids["engineer"])
        assert engineer.patch(target, json={"role": "administrator"}).status_code == 403
        final = ADMIN + "/users/" + str(ids["administrator"])
        assert admin.patch(final, json={"active": False}).status_code == 409
        assert admin.patch(final, json={"role": "viewer"}).status_code == 409
        status = admin.patch(target, json={"role": "viewer"})
        assert status.status_code == 200 and status.json()["role"] == "viewer"
        assert engineer.get(AUTH + "/me").status_code == 401
        audit = admin.get(ADMIN + "/audit").json()
        assert any(item["kind"] == "user_role_changed" for item in audit)


def test_conversation_scope_including_legacy_adoption(world):
    store, ids, browser = world
    with (
        browser("engineer") as owner,
        browser("other") as other,
        browser("administrator") as admin,
    ):
        created = owner.post(CONVERSATIONS, json={"title": "Unique private workspace"})
        assert created.status_code == 201, created.text
        path = CONVERSATIONS + "/" + created.json()["id"]
        assert owner.get(path).status_code == 200
        for foreign in (other, admin):
            assert (
                foreign.get(CONVERSATIONS, params={"q": "Unique private"}).json()[
                    "items"
                ]
                == []
            )
            assert foreign.get(path).status_code == 404
            assert foreign.get(path + "/messages").status_code == 404
            assert foreign.patch(path, json={"archived": True}).status_code == 404
            assert (
                foreign.delete(
                    path, params={"confirm": created.json()["id"]}
                ).status_code
                == 404
            )
            assert (
                foreign.post(
                    path + "/messages/stream",
                    json={
                        "question": "Review this asset.",
                        "request_id": str(uuid4()),
                    },
                ).status_code
                == 404
            )
            assert (
                foreign.post(path + "/requests/" + str(uuid4()) + "/cancel").status_code
                == 404
            )
        with store.factory.begin() as db:
            legacy = Conversation(title="Legacy report")
            db.add(legacy)
            db.flush()
            legacy_id = str(legacy.id)
        assert owner.get(CONVERSATIONS + "/" + legacy_id).status_code == 404
        assert admin.get(ADMIN + "/orphan-conversations").json()[0]["id"] == legacy_id
        orphan = ADMIN + "/orphan-conversations/" + legacy_id
        assert (
            admin.patch(
                orphan, json={"action": "adopt", "owner_id": str(ids["viewer"])}
            ).status_code
            == 422
        )
        assert admin.patch(orphan, json={"action": "archive"}).json()["archived"]
        assert (
            admin.patch(
                orphan, json={"action": "adopt", "owner_id": str(ids["engineer"])}
            ).status_code
            == 200
        )
        assert owner.get(CONVERSATIONS + "/" + legacy_id).status_code == 200
        assert other.get(CONVERSATIONS + "/" + legacy_id).status_code == 404


def test_service_scope_size_caps_and_copilot_throttle(world, monkeypatch):
    store, ids, browser = world
    monkeypatch.setenv("FLEETMIND_COPILOT_PROVIDER", "disabled")
    secret, identifier = store.new_service("fixture-simulator", 1, ids["administrator"])
    with (
        browser() as service,
        browser("engineer") as engineer,
        browser("administrator") as admin,
    ):
        service.headers["Authorization"] = "Bearer " + secret
        assert service.get("/api/v1/predictions").status_code == 403
        assert service.post("/api/v1/predict", json={}).status_code == 422
        reading = {
            "source": "manual",
            "machine_type": "L",
            "air_temperature_k": 300,
            "process_temperature_k": 310,
            "rotational_speed_rpm": 1500,
            "torque_nm": 40,
            "tool_wear_min": 120,
        }
        assert service.post("/api/v1/predict", json=reading).status_code == 403
        reading["source"] = "simulated"
        submitted = service.post("/api/v1/predict", json=reading)
        assert (
            submitted.status_code == 201 and submitted.json()["source"] == "simulated"
        )
        assert admin.get(ADMIN + "/service-credentials").json()[0]["id"] == str(
            identifier
        )
        assert (
            admin.delete(ADMIN + "/service-credentials/" + str(identifier)).status_code
            == 204
        )
        assert service.post("/api/v1/predict", json={}).status_code == 401
        chat = "/api/v1/copilot/chat"
        assert engineer.post(chat, json={"question": "x" * 9000}).status_code == 413
        for _ in range(11):
            assert (
                engineer.post(
                    chat, json={"question": "How does this model work?"}
                ).status_code
                == 503
            )
        limited = engineer.post(chat, json={"question": "How does this model work?"})
        assert limited.status_code == 429 and limited.headers["retry-after"]


def test_revoked_session_stops_live_telemetry(world, monkeypatch):
    store, _, browser = world
    with browser("viewer") as viewer:
        token = viewer.cookies["fleetmind_session"]
        principal = store.authenticate(token)
        request = Request({"type": "http"})
        request.state.stream_session = StreamSession(store, principal, token, "viewer")

        class Reader:
            def tail(self):
                return 0

            def read(self, *args):
                raise AssertionError(
                    "Revoked stream must stop before reading assessments"
                )

        async def scenario():
            slots = BoundedSemaphore(1)
            async with aclosing(
                committed_stream(request, Reader(), FeedFilter(), None, slots=slots)
            ) as stream:
                assert b"event: ready" in await anext(stream)
                store.revoke(principal, principal.session_id)
                request.state.stream_session.last -= 4
                monkeypatch.setattr(Request, "is_disconnected", connected)
                assert b"event: session_expired" in await anext(stream)
            assert slots.acquire(blocking=False)

        async def connected(_):
            return False

        asyncio.run(scenario())


def test_security_settings_require_secure_trusted_origin(world, monkeypatch):
    monkeypatch.setenv("FLEETMIND_AUTH_INSECURE_LOCAL_HTTP", "0")
    monkeypatch.setenv("FLEETMIND_AUTH_ORIGINS", "http://example.test")
    with pytest.raises(ValueError):
        SecuritySettings.from_environment()
    monkeypatch.setenv("FLEETMIND_AUTH_ORIGINS", "https://fleetmind.example")
    settings = SecuritySettings.from_environment()
    monkeypatch.setitem(app.state._state, "security_settings", settings)
    response = TestClient(app).post(
        AUTH + "/login",
        json={
            "username": "engineer-test",
            "password": PASSWORD,
        },
        headers={"Origin": "https://fleetmind.example"},
    )
    assert response.status_code == 200
    session, csrf = response.headers.get_list("set-cookie")
    assert session.startswith("__Host-fleetmind_session=")
    assert "HttpOnly" in session and "Secure" in session and "Path=/" in session
    assert csrf.startswith("__Host-fleetmind_csrf=") and "Secure" in csrf
    assert response.headers["strict-transport-security"]


def test_copilot_revocation_cancels_pending_message(world, monkeypatch):
    security, ids, browser = world
    with browser("engineer") as client:
        token = client.cookies["fleetmind_session"]
        principal = security.authenticate(token)
        assert principal is not None
        store = ConversationStore(security.factory, ids["engineer"])
        conversation = store.create(ConversationCreate(title="Interrupted stream"))
        payload = MessageInput(request_id=uuid4(), question="Review this assessment.")
        reservation = store.reserve(conversation.id, payload, 20)
        request = Request({"type": "http"})
        request.state.stream_session = StreamSession(
            security, principal, token, "engineer"
        )

        async def connected(_):
            return False

        monkeypatch.setattr(Request, "is_disconnected", connected)

        async def scenario():
            cancelled = asyncio.Event()

            class WaitingOrchestrator:
                def __init__(self, provider, executor, settings, on_event):
                    self.emit = on_event

                async def chat(self, question, context):
                    self.emit("evidence", count=0)
                    try:
                        await asyncio.Future()
                    finally:
                        cancelled.set()

            monkeypatch.setattr(streaming, "Orchestrator", WaitingOrchestrator)
            async with aclosing(
                streaming.conversation_stream(
                    request,
                    store,
                    conversation.id,
                    reservation,
                    None,
                    None,
                    Settings(),
                    None,
                )
            ) as events:
                assert b"event: started" in await anext(events)
                assert b"event: evidence" in await anext(events)
                security.revoke(principal, principal.session_id)
                request.state.stream_session.last -= 4
                assert b"event: session_expired" in await anext(events)
            assert cancelled.is_set()

        asyncio.run(scenario())
        assert store.state(conversation.id, payload.request_id) == "cancelled"
        assert [
            item.role for item in store.messages(conversation.id, 20, None).items
        ] == ["user"]
