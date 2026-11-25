"""Public inference preserves scores and restricts the standalone API."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from fleetmind.hosted import app

SENSORS = (
    "machine_type",
    "air_temperature_k",
    "process_temperature_k",
    "rotational_speed_rpm",
    "torque_nm",
    "tool_wear_min",
)
FIXTURE = json.loads(
    Path("frontend/src/data/portfolio.json").read_text(encoding="utf-8")
)


def reading(row):
    return {key: row[key] for key in SENSORS}


def test_inference_matches_frozen_fixture():
    with TestClient(app) as client:
        for row in FIXTURE["predictions"][::12]:
            response = client.post("/infer", json=reading(row))
            assert response.status_code == 200
            result = response.json()
            expected = {
                key: row[key]
                for key in ["alert_level", "predicted_failure", "model_version"]
            }
            assert {key: result[key] for key in expected} == expected
            assert abs(result["failure_score"] - row["failure_score"]) <= 1e-6
            assert "prediction_id" not in result


def test_public_runtime_rejects_invalid_and_unbounded_input():
    payload = reading(FIXTURE["predictions"][0])
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        for path in ("/docs", "/metrics", "/api/v1/predict", "/openapi.json"):
            assert client.get(path).status_code == 404
        assert client.post("/infer", content=b"{}").status_code == 415
        payloads = [
            payload | {"asset_id": "private-id"},
            payload | {"rotational_speed_rpm": "1500"},
            payload | {"air_temperature_k": 500},
        ]
        for invalid in payloads:
            assert client.post("/infer", json=invalid).status_code == 422
        body = iter([b" " * 1500, b" " * 549])
        res = client.post(
            "/infer", content=body, headers={"Content-Type": "application/json"}
        )
        assert res.status_code == 413


def test_public_rate_limit_is_process_wide(monkeypatch):
    monkeypatch.setattr("fleetmind.hosted.REQUESTS_PER_MINUTE", 2)
    payload = reading(FIXTURE["predictions"][0])
    with TestClient(app) as client:
        assert client.post("/infer", json=payload).status_code == 200
        assert client.post("/infer", json=payload).status_code == 200
        limited = client.post("/infer", json=payload)
        assert limited.status_code == 429
        assert int(limited.headers["Retry-After"]) > 0
