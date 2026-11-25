import asyncio
import logging
from secrets import token_urlsafe

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from fleetmind.api.main import app
from fleetmind.db.database import Base, get_db
from fleetmind.observability import REGISTRY, SSE, SSE_CLOSED, RequestMetrics, logger


def test_scrape_auth_and_model_health_role_boundaries(
    auth_client, monkeypatch, tmp_path
):
    reserved = token_urlsafe(32)
    token = tmp_path / "scrape.token"
    token.write_text(reserved, encoding="ascii")
    monkeypatch.setenv("FLEETMIND_METRICS_TOKEN_FILE", str(token))
    monkeypatch.setattr("fleetmind.api.main.probe_database", lambda: None)
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    def session():
        with factory() as db:
            yield db

    monkeypatch.setitem(app.dependency_overrides, get_db, session)
    with auth_client(factory, role="viewer") as viewer:
        assert viewer.get("/metrics").status_code == 404
        assert (
            viewer.get(
                "/metrics", headers={"Authorization": "Bearer invalid"}
            ).status_code
            == 404
        )
        scrape = viewer.get("/metrics", headers={"Authorization": f"Bearer {reserved}"})
        assert scrape.status_code == 200
        assert "fleetmind_process_cpu_seconds_total" in scrape.text
        assert reserved not in scrape.text
        assert TestClient(app).get("/api/v1/model/health").status_code == 401
        health = viewer.get("/api/v1/model/health?source=simulated&hours=24")
        assert health.status_code == 200
        assert health.json()["minimum_observations"] == 100
        assert viewer.get("/api/v1/model/health?hours=999").status_code == 422
        assert viewer.get("/api/v1/model/health?source=bogus").status_code == 422
        assert viewer.get("/api/v1/telemetry/dead-letters").status_code == 403
    engine.dispose()


def request_totals():
    return {
        tuple(sorted(sample.labels.items())): sample.value
        for family in REGISTRY.collect()
        if family.name == "fleetmind_http_requests"
        for sample in family.samples
        if sample.name.endswith("_total")
    }


def test_correlation_has_no_raw_paths_tokens_or_untrusted_fields(
    auth_client,
    caplog,
    monkeypatch,
):
    marker = "FLEETMIND_PRIVATE_OPERATION_STRING"
    with auth_client() as client:
        monkeypatch.setattr(logger, "propagate", True)
        before = request_totals()
        with caplog.at_level(logging.INFO, logger=logger.name):
            for i in range(10):
                response = client.get(
                    f"/invented/{marker}{i}?q={marker}",
                    headers={
                        "X-Request-ID": marker,
                    },
                )
                assert response.status_code == 404
                identifier = response.headers["x-request-id"]
                assert len(identifier) == 32 and int(identifier, 16) >= 0
            valid = "a" * 32
            confirmed = client.get("/api/v1/auth/me", headers={"X-Request-ID": valid})
            assert confirmed.headers["x-request-id"] == valid
        changed = {
            labels: count - before.get(labels, 0)
            for labels, count in request_totals().items()
        }
        not_found = [
            count
            for labels, count in changed.items()
            if dict(labels)["status"] == "404" and count
        ]
        assert not_found == [10]
        assert marker not in caplog.text
        assert "fleetmind_session" not in caplog.text
        assert "duration_ms" in caplog.text and valid in caplog.text


def test_sse_disconnect_and_request_without_response_are_counted_separately():
    async def disconnected(scope, receive, send):
        assert (await receive())["type"] == "http.disconnect"

    async def receive():
        return {"type": "http.disconnect"}

    async def send(_message):
        pass

    scope = {"type": "http", "method": "GET", "path": "/masked", "headers": []}
    before = (
        REGISTRY.get_sample_value(
            "fleetmind_http_requests_total",
            {
                "method": "GET",
                "route": "unmatched",
                "status": "no_response",
            },
        )
        or 0
    )
    asyncio.run(RequestMetrics(disconnected)(scope, receive, send))
    assert (
        REGISTRY.get_sample_value(
            "fleetmind_http_requests_total",
            {
                "method": "GET",
                "route": "unmatched",
                "status": "no_response",
            },
        )
        == before + 1
    )

    async def streaming(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/event-stream")],
            }
        )
        assert SSE.labels("telemetry")._value.get() == 1

    labels = {"stream": "telemetry", "outcome": "interrupted"}
    baseline = SSE_CLOSED.labels(**labels)._value.get()
    asyncio.run(RequestMetrics(streaming)(scope, receive, send))
    assert SSE.labels("telemetry")._value.get() == 0
    assert SSE_CLOSED.labels(**labels)._value.get() == baseline + 1
