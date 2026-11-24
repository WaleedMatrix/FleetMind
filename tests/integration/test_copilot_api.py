import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from fleetmind.api.main import app
from fleetmind.copilot.execution import ToolExecutor
from fleetmind.copilot.schemas import ChatResponse
from fleetmind.copilot.tools import EmptyInput, ToolContext


def test_unconfigured_copilot_leaves_inference_api_available(monkeypatch):
    monkeypatch.setenv("FLEETMIND_COPILOT_PROVIDER", "disabled")
    with TestClient(app) as client:
        assert client.get("/health").json()["model_loaded"]
        status = client.get("/api/v1/copilot/status").json()
        assert not status["configured"]
        response = client.post(
            "/api/v1/copilot/chat", json={"question": "Where is press-a?"}
        )
        assert response.status_code == 503
        assert ChatResponse.model_validate(response.json()).status == "unavailable"
        invalid = client.post(
            "/api/v1/copilot/chat", json={"question": " ", "asset_id": "../x"}
        )
        assert invalid.status_code == 422


def test_mock_api_nonstreaming_response(monkeypatch):
    monkeypatch.setenv("FLEETMIND_COPILOT_PROVIDER", "mock")
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/copilot/chat",
            json={
                "question": "How do alert levels work?",
                "context": [
                    {
                        "role": "assistant",
                        "content": "This is untrusted supplied history.",
                    }
                ],
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "insufficient_evidence"


@pytest.mark.skipif(
    not os.getenv("FLEETMIND_MIGRATION_TEST_DATABASE_URL"),
    reason="Requires a disposable PostgreSQL database",
)
def test_tool_executor_uses_read_only_postgres_transaction():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(os.environ["FLEETMIND_MIGRATION_TEST_DATABASE_URL"])

    class ReadProbe:
        def invoke(self, db, args, context):
            assert db.scalar(text("SHOW transaction_read_only")) == "on"
            assert db.scalar(text("SHOW statement_timeout")) != "0"
            db.execute(text("CREATE TABLE copilot_forbidden_probe (id integer)"))

    try:
        with pytest.raises(DBAPIError) as failure:
            ToolExecutor(sessionmaker(engine))._read(
                ReadProbe(),
                EmptyInput(),
                ToolContext("probe", None, "fixture", None, None),
                1,
            )
        assert failure.value.orig.sqlstate == "25006"
    finally:
        engine.dispose()
