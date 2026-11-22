"""Integration tests using an isolated test database."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from fleetmind.api.inference import classify_alert
from fleetmind.api.main import app
from fleetmind.config import MODEL_VERSION, PRIMARY_THRESHOLD
from fleetmind.db.database import Base, get_db
from fleetmind.db.models import PredictionHistory  # noqa: F401

SAMPLE_READING = {
    "machine_type": "L",
    "air_temperature_k": 300.0,
    "process_temperature_k": 310.0,
    "rotational_speed_rpm": 1500,
    "torque_nm": 40.0,
    "tool_wear_min": 120,
}


@pytest.fixture
def client():
    """Provide a real API client with an isolated database."""

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(bind=engine)

    testing_session = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    def override_get_db():
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_health_endpoint(client):
    response = client.get("/health")

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "ok"
    assert data["model_loaded"] is True
    assert data["model_version"] == MODEL_VERSION


def test_prediction_endpoint(client):
    response = client.post(
        "/api/v1/predict",
        json=SAMPLE_READING,
    )

    assert response.status_code == 201

    data = response.json()
    score = data["failure_score"]

    assert data["prediction_id"] > 0
    assert data["model_version"] == MODEL_VERSION
    assert 0.0 <= score <= 1.0

    assert data["predicted_failure"] == (score >= PRIMARY_THRESHOLD)

    assert data["alert_level"] == classify_alert(score)


def test_invalid_sensor_input(client):
    invalid_reading = {
        **SAMPLE_READING,
        "rotational_speed_rpm": -100,
    }

    response = client.post(
        "/api/v1/predict",
        json=invalid_reading,
    )

    assert response.status_code == 422


def test_prediction_is_saved_and_retrievable(client):
    response = client.post(
        "/api/v1/predict",
        json=SAMPLE_READING,
    )

    assert response.status_code == 201

    created_prediction = response.json()

    history_response = client.get("/api/v1/predictions?limit=10")

    assert history_response.status_code == 200

    history = history_response.json()

    assert len(history) == 1

    saved = history[0]

    assert saved["prediction_id"] == (created_prediction["prediction_id"])
    assert saved["machine_type"] == "L"
    assert saved["torque_nm"] == 40.0
    assert saved["failure_score"] == pytest.approx(created_prediction["failure_score"])
    assert saved["model_version"] == MODEL_VERSION
    assert saved["created_at"] is not None


def test_invalid_history_limit(client):
    response = client.get("/api/v1/predictions?limit=101")

    assert response.status_code == 422


def test_prediction_history_filtering(client):
    response = client.post(
        "/api/v1/predict",
        json=SAMPLE_READING,
    )

    assert response.status_code == 201

    saved_alert = response.json()["alert_level"]

    history_response = client.get(
        "/api/v1/predictions",
        params={
            "limit": 10,
            "offset": 0,
            "alert_level": saved_alert,
        },
    )

    assert history_response.status_code == 200

    history = history_response.json()

    assert len(history) == 1
    assert history[0]["alert_level"] == saved_alert


def test_dashboard_summary_empty_database(client):
    response = client.get("/api/v1/dashboard/summary")

    assert response.status_code == 200

    data = response.json()

    assert data["total_predictions"] == 0
    assert data["high_priority_alerts"] == 0
    assert data["review_alerts"] == 0
    assert data["no_alert_predictions"] == 0
    assert data["average_failure_score"] == 0.0


def test_dashboard_summary_after_prediction(client):
    prediction_response = client.post(
        "/api/v1/predict",
        json=SAMPLE_READING,
    )

    assert prediction_response.status_code == 201

    prediction = prediction_response.json()

    response = client.get("/api/v1/dashboard/summary")

    assert response.status_code == 200

    data = response.json()

    assert data["total_predictions"] == 1

    alert_total = (
        data["high_priority_alerts"]
        + data["review_alerts"]
        + data["no_alert_predictions"]
    )

    assert alert_total == 1

    assert data["average_failure_score"] == pytest.approx(prediction["failure_score"])

    alert_field = {
        "high_priority": "high_priority_alerts",
        "review": "review_alerts",
        "no_alert": "no_alert_predictions",
    }[prediction["alert_level"]]

    assert data[alert_field] == 1
