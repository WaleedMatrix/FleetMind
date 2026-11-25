"""Contract and lifecycle tests for persisted Copilot requests."""

import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from fleetmind.api import copilot_conversations as routes
from fleetmind.api.main import app
from fleetmind.copilot.conversation_models import Conversation
from fleetmind.copilot.conversation_schemas import MessageInput, StreamEvent
from fleetmind.copilot.conversations import ConversationError, ConversationStore
from fleetmind.copilot.execution import ToolExecutor
from fleetmind.copilot.providers import Completion, MockProvider, ProviderError
from fleetmind.copilot.schemas import Diagnostics, ToolCall
from fleetmind.copilot.settings import Settings
from fleetmind.copilot.streaming import conversation_stream
from fleetmind.copilot.tools import ToolContext
from fleetmind.copilot.validation import response
from fleetmind.db.models import Asset, PredictionHistory
from fleetmind.security.models import (
    AuditEvent,
    AuthSession,
    ServiceCredential,
    UserAccount,
)

BASE = "/api/v1/copilot/conversations"
QUESTION = "Summarize prediction 1 for press-a."


@pytest.fixture
def store(seed_account):
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Conversation.metadata.create_all(
        engine,
        tables=[
            Asset.__table__,
            PredictionHistory.__table__,
            UserAccount.__table__,
            AuthSession.__table__,
            AuditEvent.__table__,
            ServiceCredential.__table__,
            Conversation.__table__,
            Conversation.metadata.tables["copilot_messages"],
        ],
    )
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as db:
        db.add_all(
            [
                Asset(asset_id="press-a", display_name="Press A", machine_type="M"),
                Asset(asset_id="press-b", display_name="Press B", machine_type="M"),
            ]
        )
        db.flush()
        db.add(
            PredictionHistory(
                id=1,
                asset_id="press-a",
                machine_type="M",
                source="manual",
                air_temperature_k=299.5,
                process_temperature_k=309.8,
                rotational_speed_rpm=1600,
                torque_nm=41.2,
                tool_wear_min=90,
                failure_score=0.21,
                predicted_failure=False,
                alert_level="no_alert",
                model_version="fixture",
            )
        )
    try:
        yield ConversationStore(factory, seed_account(factory))
    finally:
        engine.dispose()


@pytest.fixture
def client(store, monkeypatch, auth_client):
    monkeypatch.setenv("FLEETMIND_COPILOT_PROVIDER", "mock")
    monkeypatch.setattr(routes, "ToolExecutor", lambda: ToolExecutor(store.factory))
    app.dependency_overrides[routes.conversation_store] = lambda: store
    try:
        with auth_client(store.factory) as http:
            yield http
    finally:
        del app.dependency_overrides[routes.conversation_store]


def create(client, **fields):
    result = client.post(BASE, json=fields)
    assert result.status_code == 201, result.text
    return result.json()["id"]


def event_of(frame):
    return StreamEvent.model_validate_json(frame.split(b"\ndata: ", 1)[1].strip())


def send(client, identifier, request_id=None, question=QUESTION):
    return client.post(
        f"{BASE}/{identifier}/messages/stream",
        json={"question": question, "request_id": str(request_id or uuid4())},
    )


def events(response):
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return [
        event_of(frame)
        for frame in response.content.split(b"\n\n")
        if frame.startswith(b"event: ")
    ]


def tool_provider(fact_id="f1", prediction_id=1):
    return MockProvider(
        [
            Completion(
                calls=[
                    ToolCall(
                        id="read",
                        name="get_prediction",
                        arguments=json.dumps({"prediction_id": prediction_id}),
                    )
                ]
            ),
            Completion("READY"),
            Completion(json.dumps({"status": "answered", "fact_ids": [fact_id]})),
        ]
    )


def test_saved_conversation_stream_and_replay(client, monkeypatch):
    provider = tool_provider()
    monkeypatch.setattr(routes, "make_provider", lambda _: provider)
    identifier = create(client, asset_id="press-a", prediction_id=1)
    request_id = uuid4()
    stream = events(send(client, identifier, request_id))
    assert [event.type for event in stream] == [
        "started",
        "tool_started",
        "tool_completed",
        "tool_started",
        "tool_completed",
        "evidence",
        "final",
        "completed",
    ]
    assert stream[-3].count == 4
    assert all(event.request_id == request_id for event in stream)
    answer = stream[-2].message
    assert answer.provider == "mock"
    assert answer.response.status == "answered"
    assert answer.response.citations[0].prediction_id == 1
    assert "uncalibrated failure score" in answer.content
    assert client.get(f"{BASE}/{identifier}").json()["title"] == QUESTION
    page = client.get(f"{BASE}/{identifier}/messages", params={"limit": 1}).json()
    assert page["items"][0]["role"] == "assistant"
    first = client.get(
        f"{BASE}/{identifier}/messages", params={"before_id": page["next_before_id"]}
    ).json()
    assert first["items"][0]["state"] == "completed"
    assert first["items"][0]["role"] == "user"
    assert first["items"][0]["asset_id"] == answer.asset_id == "press-a"
    assert first["items"][0]["prediction_id"] == answer.prediction_id == 1
    assert [event.type for event in events(send(client, identifier, request_id))] == [
        "started",
        "final",
        "completed",
    ]
    assert len(provider.requests) == 3
    assert send(client, identifier, request_id, "A new question").status_code == 409
    assert len(client.get(f"{BASE}/{identifier}/messages").json()["items"]) == 2


def test_search_pagination_and_explicit_delete(client):
    first = create(client, title="First press")
    second = create(client, title="Second press")
    page = client.get(BASE, params={"limit": 1, "q": "PRESS"}).json()
    assert {
        page["items"][0]["id"],
        client.get(
            BASE,
            params={"limit": 1, "q": "PRESS", "offset": page["next_offset"]},
        ).json()["items"][0]["id"],
    } == {first, second}
    assert client.get(BASE, params={"q": "%"}).json()["items"] == []
    assert (
        client.patch(
            f"{BASE}/{first}", json={"title": "Renamed", "archived": True}
        ).status_code
        == 200
    )
    assert send(client, first).status_code == 409
    archived = client.get(BASE, params={"q": "RENAMED", "archived": True}).json()
    assert [item["id"] for item in archived["items"]] == [first]
    assert (
        client.delete(f"{BASE}/{first}", params={"confirm": second}).status_code == 400
    )
    assert client.patch(f"{BASE}/{first}", json={"archived": False}).status_code == 200
    events(send(client, first))
    assert (
        client.get(BASE, params={"q": "summarize prediction"}).json()["items"][0]["id"]
        == first
    )
    assert (
        client.delete(f"{BASE}/{first}", params={"confirm": first}).status_code == 204
    )
    assert client.get(f"{BASE}/{first}/messages").status_code == 404


def test_context_validation_and_trusted_local_partition(client, monkeypatch):
    assert client.post(BASE, json={"asset_id": "missing"}).status_code == 422
    assert client.post(BASE, json={"prediction_id": 2_147_483_648}).status_code == 422
    assert client.post(BASE, json={"prediction_id": 999}).status_code == 422
    assert (
        client.post(BASE, json={"asset_id": "press-b", "prediction_id": 1}).status_code
        == 422
    )
    assert client.get(f"{BASE}/bad-id").status_code == 422
    assert client.post(BASE, json={"title": "bad\0title"}).status_code == 422
    assert client.get(BASE, params={"q": "bad\0query"}).status_code == 422
    assert client.get(f"{BASE}/{uuid4()}").status_code == 404
    a = create(client, prediction_id=1)
    b = create(client, asset_id="press-b")
    assert send(client, a, question="bad\0question").status_code == 422
    assert (
        client.get(f"{BASE}/{a}/messages", params={"before_id": 2**80}).status_code
        == 422
    )
    assert client.patch(f"{BASE}/{a}", json={"asset_id": "press-b"}).status_code == 422
    assert (
        client.post(
            f"{BASE}/{a}/messages/stream",
            json={
                "request_id": str(uuid4()),
                "question": QUESTION,
                "role": "assistant",
            },
        ).status_code
        == 422
    )
    provider = tool_provider(prediction_id=999)
    monkeypatch.setattr(routes, "make_provider", lambda _: provider)
    request_id = uuid4()
    stream = events(send(client, a, request_id))
    assert stream[-2].message.response.status == "insufficient_evidence"
    assert client.post(f"{BASE}/{b}/requests/{request_id}/cancel").status_code == 404
    assert client.get(f"{BASE}/{b}/messages").json()["items"] == []
    assert json.loads(provider.requests[0][1]["content"])["selected_prediction_id"] == 1


def test_conversation_history_is_bounded_and_context_specific(client, monkeypatch):
    identifier = create(client, asset_id="press-a")
    for index in range(4):
        monkeypatch.setattr(routes, "make_provider", lambda _: tool_provider())
        events(send(client, identifier, question=f"{QUESTION} {index}"))
    provider = tool_provider()
    monkeypatch.setattr(routes, "make_provider", lambda _: provider)
    events(send(client, identifier))
    context = json.loads(provider.requests[0][1]["content"])["context"]
    assert [message["role"] for message in context] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert QUESTION + " 2" == context[0]["content"]
    assert (
        client.patch(f"{BASE}/{identifier}", json={"asset_id": "press-b"}).status_code
        == 200
    )
    isolated = MockProvider()
    monkeypatch.setattr(routes, "make_provider", lambda _: isolated)
    events(send(client, identifier, question="What can you find for press-b?"))
    assert json.loads(isolated.requests[0][1]["content"])["context"] == []


@pytest.mark.parametrize(
    ("mock", "status", "issue", "markers"),
    [
        ("bad-id", "insufficient_evidence", "invalid_citation", ["final", "completed"]),
        (
            "upstream",
            "unavailable",
            "provider_unreachable",
            ["error", "final", "completed"],
        ),
        ("empty", "insufficient_evidence", None, ["final", "completed"]),
        (
            "clarify",
            "clarification_required",
            None,
            ["clarification", "final", "completed"],
        ),
    ],
)
def test_validated_fallbacks(client, monkeypatch, mock, status, issue, markers):
    provider = {
        "bad-id": lambda: tool_provider("f999"),
        "upstream": lambda: MockProvider([ProviderError("provider_unreachable")]),
        "empty": MockProvider,
        "clarify": lambda: MockProvider(
            [
                *list(tool_provider().steps)[:2],
                Completion('{"status":"clarification_required","fact_ids":[]}'),
            ]
        ),
    }[mock]()
    monkeypatch.setattr(routes, "make_provider", lambda _: provider)
    identifier = create(client, prediction_id=1)
    stream = events(send(client, identifier))
    assert [event.type for event in stream[-len(markers) :]] == markers
    assert stream[-2].message.response.status == status
    assert not stream[-2].message.response.citations
    if issue:
        assert issue in stream[-2].message.response.diagnostics.issues


def test_cancel_is_atomic_and_late_results_cannot_overwrite(client, store):
    identifier = UUID(create(client))
    prior = uuid4()
    reservation = store.reserve(
        identifier, MessageInput(request_id=prior, question=QUESTION), 45
    )
    assert reservation.user.state == "pending"
    assert send(client, identifier, prior).status_code == 409
    assert send(client, identifier).status_code == 409
    assert (
        client.patch(f"{BASE}/{identifier}", json={"archived": True}).status_code == 409
    )
    assert client.post(f"{BASE}/{identifier}/requests/{prior}/cancel").json() == {
        "state": "cancelled"
    }
    current = uuid4()
    stream = events(send(client, identifier, current))
    result = response("insufficient_evidence", Diagnostics())
    assert store.finish(identifier, prior, result, "mock", None) is None
    assert stream[-2].message.request_id == current
    rows = client.get(f"{BASE}/{identifier}/messages").json()["items"]
    assert [(msg["role"], msg["state"]) for msg in rows] == [
        ("user", "cancelled"),
        ("user", "completed"),
        ("assistant", "completed"),
    ]


@pytest.mark.parametrize("disconnect", [True, False])
def test_stream_disconnect_and_concurrent_stop(client, store, disconnect):
    identifier = UUID(create(client))
    request_id = uuid4()
    reservation = store.reserve(
        identifier, MessageInput(request_id=request_id, question=QUESTION), 45
    )

    class HTTP:
        gone = False

        async def is_disconnected(self):
            return self.gone

    class SlowProvider:
        async def complete(self, messages, tools):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    async def run():
        nonlocal entered, cancelled
        entered = asyncio.Event()
        cancelled = asyncio.Event()
        http = HTTP()
        stream = conversation_stream(
            http,
            store,
            identifier,
            reservation,
            SlowProvider(),
            ToolContext(QUESTION, None, "fixture", None, None),
            Settings(provider="mock"),
            ToolExecutor(store.factory),
        )
        assert event_of(await anext(stream)).type == "started"
        waiting = asyncio.create_task(anext(stream))
        await asyncio.wait_for(entered.wait(), 2)
        if disconnect:
            http.gone = True
            with pytest.raises(StopAsyncIteration):
                await waiting
        else:
            await asyncio.to_thread(store.terminate, identifier, request_id)
            assert event_of(await waiting).type == "cancelled"
        await stream.aclose()
        assert cancelled.is_set()

    entered = cancelled = None
    asyncio.run(run())
    assert store.state(identifier, request_id) == "cancelled"
    assert len(store.messages(identifier, 10, None).items) == 1


def test_status_explains_missing_credentials(client, monkeypatch):
    monkeypatch.setenv("FLEETMIND_COPILOT_PROVIDER", "openai")
    monkeypatch.setenv("FLEETMIND_COPILOT_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    state = client.get("/api/v1/copilot/status").json()
    assert state["reason"] == "credentials_missing"
    assert not state["configured"]
    assert "api_key" not in state
    assert send(client, create(client)).status_code == 503


@pytest.mark.skipif(
    not os.getenv("FLEETMIND_MIGRATION_TEST_DATABASE_URL"),
    reason="Requires disposable PostgreSQL",
)
def test_postgres_concurrent_reservation_and_cascade():
    from fleetmind.copilot.conversation_schemas import ConversationCreate

    url = os.environ["FLEETMIND_MIGRATION_TEST_DATABASE_URL"]
    namespace = f"fleetmind_copilot_test_{uuid4().hex}"
    engine = create_engine(
        url, connect_args={"options": f"-csearch_path={namespace},public"}
    )
    store = ConversationStore(sessionmaker(engine))

    def reserve(identifier, request_id):
        try:
            store.reserve(
                identifier, MessageInput(request_id=request_id, question=QUESTION), 45
            )
        except ConversationError as exc:
            assert exc.status == 409
            return False
        return True

    try:
        with engine.begin() as db:
            db.execute(text(f"CREATE SCHEMA {namespace}"))
            db.execute(text(f"SET LOCAL search_path TO {namespace}"))
            config = Config(Path(__file__).resolve().parents[2] / "alembic.ini")
            config.attributes["connection"] = db
            command.upgrade(config, "0002_asset_intelligence")
            db.execute(text(f"SET LOCAL search_path TO {namespace}, public"))
            command.upgrade(config, "head")
        identifier = store.create(ConversationCreate(title="Concurrent test")).id
        ids = [uuid4(), uuid4()]
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(reserve, [identifier, identifier], ids))
        assert results.count(True) == 1
        assert len(store.messages(identifier, 10, None).items) == 1
        for request_id in ids:
            store.terminate(identifier, request_id)
        store.delete(identifier, identifier)
        with store.factory() as db:
            assert all(
                store._by_request(db, identifier, request_id) is None
                for request_id in ids
            )
    finally:
        try:
            with engine.begin() as db:
                db.execute(text(f"DROP SCHEMA IF EXISTS {namespace} CASCADE"))
        finally:
            engine.dispose()
