"""Integration tests using an isolated test database."""

import json
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from fleetmind.api.inference import classify_alert
from fleetmind.api.main import PROJECT_ROOT, app
from fleetmind.api.model_intelligence import (
    ExplanationResponse,
    ModelIntelligenceResponse,
)
from fleetmind.config import MODEL_VERSION, PRIMARY_THRESHOLD
from fleetmind.data.split import FEATURES
from fleetmind.db.database import Base, get_db
from fleetmind.db.models import PredictionHistory
from fleetmind.features.engineering import THERMAL_GAP

SAMPLE_READING = {
    "machine_type": "L",
    "air_temperature_k": 300.0,
    "process_temperature_k": 310.0,
    "rotational_speed_rpm": 1500,
    "torque_nm": 40.0,
    "tool_wear_min": 120,
}
PRESS = {
    "asset_id": "press-01",
    "display_name": "Forming Press",
    "machine_type": "L",
    "location": "North line",
    "description": "Primary forming station",
}


@pytest.fixture
def client(auth_client):
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
        with auth_client(testing_session) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_health_endpoint(client):
    response = client.get("/health")

    assert response.status_code == 200

    assert response.json() == {"status": "ok"}
    data = client.get("/api/v1/system/status").json()

    assert data["status"] == "ok"
    assert data["model_loaded"] is True
    assert data["model_version"] == MODEL_VERSION


def test_prediction_explanation_matches_saved_score_and_raw_margin(client):
    saved = client.post("/api/v1/predict", json=SAMPLE_READING).json()
    path = f"/api/v1/predictions/{saved['prediction_id']}/explanation"
    exp = app.state.explainer
    result = client.get(path)
    assert result.status_code == 200
    explanation = ExplanationResponse.model_validate(result.json())
    assert explanation.model_version == saved["model_version"]
    assert explanation.failure_score == saved["failure_score"]
    assert explanation.output_unit == "raw_margin_log_odds"
    assert [feature.name for feature in explanation.features] == [
        *FEATURES,
        THERMAL_GAP,
    ]
    assert [feature.value for feature in explanation.features] == [
        *SAMPLE_READING.values(),
        10.0,
    ]
    assert explanation.features[0].unit is None
    assert len(explanation.features[0].transformed_features) == 3
    assert explanation.features[-1].unit == "K"
    assert explanation.features[-1].derived
    total = explanation.baseline + sum(
        item.contribution for item in explanation.features
    )
    assert total == pytest.approx(explanation.raw_output, abs=2e-5)
    assert client.get(path).json() == result.json()
    assert app.state.explainer is exp


def test_explanation_refuses_missing_incompatible_and_inconsistent_records(client):
    assert client.get("/api/v1/predictions/8123/explanation").status_code == 404
    assert client.get("/api/v1/predictions/0/explanation").status_code == 422
    created = client.post("/api/v1/predict", json=SAMPLE_READING).json()
    prediction_id = created["prediction_id"]
    get_test_session = contextmanager(app.dependency_overrides[get_db])
    with get_test_session() as db:
        record = db.get(PredictionHistory, prediction_id)
        record.model_version = "archived_model"
        db.commit()
    path = f"/api/v1/predictions/{prediction_id}/explanation"
    incompatible = client.get(path)
    assert incompatible.status_code == 409
    assert "archived_model" in incompatible.json()["detail"]
    with get_test_session() as db:
        record = db.get(PredictionHistory, prediction_id)
        record.model_version = MODEL_VERSION
        record.failure_score = 0.8 if created["failure_score"] < 0.5 else 0.1
        db.commit()
    assert client.get(path).status_code == 503


def test_inference_works_with_unavailable_explainer(client):
    explainer = app.state.explainer
    app.state.explainer = None
    try:
        predicted = client.post("/api/v1/predict", json=SAMPLE_READING)
        assert predicted.status_code == 201
        prediction_id = predicted.json()["prediction_id"]
        path = f"/api/v1/predictions/{prediction_id}/explanation"
        assert client.get(path).status_code == 503
    finally:
        app.state.explainer = explainer


def test_model_intelligence_uses_frozen_report_and_training_importance(client):
    result = client.get("/api/v1/model/intelligence")
    assert result.status_code == 200
    body = ModelIntelligenceResponse.model_validate(result.json())
    report = json.loads((PROJECT_ROOT / body.metadata.evaluation_report).read_text())
    assert body.evaluation is not None
    assert body.evaluation.average_precision == report["average_precision"]
    assert body.evaluation.test_observations == report["test_observations"]
    assert (
        body.evaluation.primary_threshold_results.true_positive
        == (report["primary_threshold_results"]["TP"])
    )
    assert body.global_importance is not None
    assert body.global_importance.model_version == MODEL_VERSION
    assert body.global_importance.dataset_sha256 == body.metadata.dataset_sha256
    assert body.global_importance.dataset_split == "training"
    assert body.global_importance.sample_size == 512
    assert [item.name for item in body.global_importance.features] == [
        *FEATURES,
        THERMAL_GAP,
    ]


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

    assert saved["prediction_id"] == created_prediction["prediction_id"]
    assert {field: saved[field] for field in SAMPLE_READING} == SAMPLE_READING
    assert saved["failure_score"] == pytest.approx(created_prediction["failure_score"])
    assert saved["model_version"] == MODEL_VERSION
    assert saved["alert_level"] == created_prediction["alert_level"]
    assert saved["created_at"] is not None
    assert saved["asset_id"] is None
    assert saved["source"] == "unknown"


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


def test_filtered_history_keeps_latest_first_across_pages(client):
    created_ids = []
    for _ in range(3):
        response = client.post("/api/v1/predict", json=SAMPLE_READING)
        assert response.status_code == 201
        saved = response.json()
        created_ids.append(saved["prediction_id"])

    params = {"limit": 2, "alert_level": saved["alert_level"]}
    for offset, expected_ids in [(0, created_ids[:0:-1]), (2, created_ids[:1])]:
        response = client.get(
            "/api/v1/predictions", params={**params, "offset": offset}
        )
        assert response.status_code == 200
        assert [row["prediction_id"] for row in response.json()] == expected_ids

    for alert in {"high_priority", "review", "no_alert"} - {saved["alert_level"]}:
        response = client.get(
            "/api/v1/predictions",
            params={**params, "alert_level": alert},
        )
        assert response.status_code == 200
        assert response.json() == []


def test_dashboard_summary_empty_database(client):
    response = client.get("/api/v1/dashboard/summary")

    assert response.status_code == 200

    data = response.json()

    assert data["total_predictions"] == 0
    assert data["high_priority_alerts"] == 0
    assert data["review_alerts"] == 0
    assert data["no_alert_predictions"] == 0
    assert data["average_failure_score"] == 0.0


def test_asset_registry_creation_search_pagination_and_update(client):
    registered = client.post("/api/v1/assets", json=PRESS)
    assert registered.status_code == 201
    assert registered.json() == {**PRESS, "created_at": registered.json()["created_at"]}
    assert client.post("/api/v1/assets", json=PRESS).status_code == 409
    other = {
        **PRESS,
        "asset_id": "motor-02",
        "display_name": "Motor",
        "machine_type": "H",
    }
    assert client.post("/api/v1/assets", json=other).status_code == 201

    query = client.get("/api/v1/assets", params={"q": "NORTH", "machine_type": "L"})
    assert [asset["asset_id"] for asset in query.json()] == ["press-01"]
    assert client.get("/api/v1/assets", params={"q": "%"}).json() == []
    assert client.get("/api/v1/assets", params={"limit": 1, "offset": 1}).json() == [
        registered.json(),
    ]
    assert client.get("/api/v1/assets?limit=101").status_code == 422

    update = client.patch(
        "/api/v1/assets/press-01", json={"display_name": "Press One", "location": None}
    )
    assert update.status_code == 200
    assert update.json()["description"] == PRESS["description"]
    assert update.json()["location"] is None
    assert client.get("/api/v1/assets/press-01").json() == update.json()
    for changes in [{"display_name": None}, {"asset_id": "new"}, {"machine_type": "H"}]:
        assert client.patch("/api/v1/assets/press-01", json=changes).status_code == 422


def test_asset_validation_and_unregistered_or_mismatched_readings(client):
    for changes in [
        {"asset_id": "../press"},
        {"display_name": "  "},
        {"machine_type": "unknown"},
    ]:
        assert (
            client.post("/api/v1/assets", json={**PRESS, **changes}).status_code == 422
        )

    for endpoint in ["", "/predictions", "/summary"]:
        assert client.get(f"/api/v1/assets/missing{endpoint}").status_code == 404
    assert (
        client.post(
            "/api/v1/predict", json={**SAMPLE_READING, "asset_id": "missing"}
        ).status_code
        == 404
    )
    assert client.post("/api/v1/assets", json=PRESS).status_code == 201
    assert (
        client.post(
            "/api/v1/predict",
            json={**SAMPLE_READING, "asset_id": "press-01", "machine_type": "M"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/predict", json={**SAMPLE_READING, "source": "bad-source"}
        ).status_code
        == 422
    )
    assert client.get("/api/v1/predictions").json() == []


def test_asset_history_and_monitoring_exclude_unassigned_and_other_assets(client):
    assert client.post("/api/v1/assets", json=PRESS).status_code == 201
    assert (
        client.post(
            "/api/v1/assets", json={**PRESS, "asset_id": "press-02"}
        ).status_code
        == 201
    )
    path = "/api/v1/assets/press-01"
    empty = client.get(f"{path}/summary").json()
    assert empty["total_predictions"] == 0
    assert empty["average_failure_score"] is None
    assert empty["last_prediction_at"] is None

    manual = client.post(
        "/api/v1/predict",
        json={**SAMPLE_READING, "asset_id": "press-01", "source": "manual"},
    )
    simulated = client.post(
        "/api/v1/predict",
        json={**SAMPLE_READING, "asset_id": "press-01", "source": "simulated"},
    )
    assert manual.status_code == simulated.status_code == 201
    manual, simulated = manual.json(), simulated.json()
    assert manual["asset_id"] == "press-01"
    assert manual["source"] == "manual"
    assert simulated["failure_score"] == manual["failure_score"]
    assert (
        client.post(
            "/api/v1/predict", json={**SAMPLE_READING, "asset_id": "press-02"}
        ).status_code
        == 201
    )
    assert client.post("/api/v1/predict", json=SAMPLE_READING).status_code == 201

    readings = client.get(f"{path}/predictions").json()
    assert [row["prediction_id"] for row in readings] == [
        simulated["prediction_id"],
        manual["prediction_id"],
    ]
    assert client.get(f"{path}/predictions?limit=1&offset=1").json() == readings[1:]
    assert client.get(f"{path}/predictions?source=simulated").json() == readings[:1]
    assert client.get("/api/v1/predictions?asset_id=press-01").json() == readings
    alerts = client.get(f"{path}/predictions?alerts_only=true").json()
    assert alerts == [row for row in readings if row["alert_level"] != "no_alert"]

    stats = client.get(f"{path}/summary").json()
    assert stats["total_predictions"] == 2
    assert stats["average_failure_score"] == pytest.approx(manual["failure_score"])
    assert stats["last_prediction_at"] == readings[0]["created_at"]
    assert stats["high_priority_alerts"] + stats["review_alerts"] == len(alerts)


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
