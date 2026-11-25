"""Prove the telemetry revision preserves legacy PostgreSQL tables and rows."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from fleetmind.api.telemetry import status
from fleetmind.db.models import Asset, PredictionHistory
from fleetmind.knowledge.embeddings import EmbeddingIdentity
from fleetmind.knowledge.ingestion import ingest
from fleetmind.knowledge.schemas import DocumentInput

TEST_URL = os.getenv("FLEETMIND_MIGRATION_TEST_DATABASE_URL")
TABLES = (
    "assets",
    "prediction_history",
    "knowledge_documents",
    "knowledge_chunks",
    "knowledge_embeddings",
    "knowledge_ingestion_events",
    "copilot_conversations",
    "copilot_messages",
)


class Encoder:
    identity = EmbeddingIdentity("fleetmind-test/fixture", "v1", 3)
    loaded_identity = identity

    def encode(self, values):
        return [[1.0, 0.0, 0.0] for _ in values]


def snapshot(connection):
    return {
        name: (
            connection.scalar(text(f"SELECT '{name}'::regclass::oid")),
            connection.execute(
                text(
                    f"SELECT to_jsonb(item)::text FROM {name} item ORDER BY 1",
                )
            )
            .scalars()
            .all(),
        )
        for name in TABLES
    }


@pytest.mark.skipif(not TEST_URL, reason="Requires an isolated PostgreSQL dev database")
def test_additive_telemetry_migration_preserves_existing_data():
    schema = f"fleetmind_telemetry_migration_{uuid4().hex}"
    engine = create_engine(TEST_URL)
    try:
        with engine.connect() as db, db.begin() as transaction:
            db.execute(text(f"CREATE SCHEMA {schema}"))
            db.execute(text(f"SET LOCAL search_path TO {schema}"))
            config = Config(Path(__file__).resolve().parents[2] / "alembic.ini")
            config.attributes["connection"] = db
            command.upgrade(config, "0002_asset_intelligence")
            db.execute(text(f"SET LOCAL search_path TO {schema}, public"))
            command.upgrade(config, "0004_copilot_conversations")
            db.execute(text(f"SET LOCAL search_path TO {schema}"))
            with Session(db, join_transaction_mode="create_savepoint") as session:
                with session.begin():
                    assert status(session).state == "migration_required"
                    session.rollback()
                db.execute(text(f"SET LOCAL search_path TO {schema}, public"))
                with session.begin():
                    session.add(
                        Asset(
                            asset_id="legacy-press",
                            display_name="Legacy press",
                            machine_type="L",
                        )
                    )
                    session.add(
                        PredictionHistory(
                            source="unknown",
                            machine_type="L",
                            air_temperature_k=298,
                            process_temperature_k=309,
                            rotational_speed_rpm=1510,
                            torque_nm=40,
                            tool_wear_min=37,
                            failure_score=0.12,
                            predicted_failure=False,
                            alert_level="no_alert",
                            model_version="legacy-fixture",
                        )
                    )
                    ingest(
                        session,
                        DocumentInput(
                            id="legacy-doc",
                            title="Legacy document",
                            category="sensors",
                            source_kind="project",
                            source_ref="docs/legacy.md",
                        ),
                        "Torque uses newton metres.",
                        "text",
                        Encoder(),
                    )

            ids = {"id": uuid4(), "request": uuid4()}
            db.execute(
                text("""
                INSERT INTO copilot_conversations (id, title)
                VALUES (:id, 'Legacy chat')
            """),
                ids,
            )
            db.execute(
                text("""
                INSERT INTO copilot_messages
                    (conversation_id, request_id, role, state, content)
                VALUES (:id, :request, 'user', 'completed', 'Legacy question')
            """),
                ids,
            )
            before = snapshot(db)
            assert all(rows for _, rows in before.values())
            command.upgrade(config, "0005_telemetry_assessments")
            assert snapshot(db) == before
            event = uuid4()
            db.execute(
                text("""
                INSERT INTO telemetry_assessments
                    (event_id, prediction_id, schema_version, event_hash,
                     observed_at, ingested_at, assessed_at)
                SELECT :event, id, 1, 'fixture', created_at, created_at, created_at
                FROM prediction_history
            """),
                {"event": event},
            )
            receipt = db.execute(text("SELECT * FROM telemetry_assessments")).one()
            command.upgrade(config, "0006_telemetry_live_monitoring")
            assert snapshot(db) == before
            assert (
                db.execute(text("SELECT * FROM telemetry_assessments")).one() == receipt
            )
            assert db.execute(
                text("SELECT position, event_id FROM telemetry_stream_events")
            ).one() == (1, event)
            with Session(db, join_transaction_mode="create_savepoint") as session:
                result = status(session)
                assert result.state == "ready" and result.persisted_assessments == 1
            command.upgrade(config, "head")
            secured = snapshot(db)
            assert {
                k: v for k, v in secured.items() if k != "copilot_conversations"
            } == {k: v for k, v in before.items() if k != "copilot_conversations"}
            assert (
                db.scalar(text("SELECT 'copilot_conversations'::regclass::oid"))
                == before["copilot_conversations"][0]
            )
            assert (
                db.scalar(
                    text(
                        "SELECT (to_jsonb(item) - 'owner_id')::text "
                        "FROM copilot_conversations item WHERE owner_id IS NULL"
                    )
                )
                == before["copilot_conversations"][1][0]
            )
            assert (
                db.execute(text("SELECT * FROM telemetry_assessments")).one() == receipt
            )
            assert db.scalar(text("SELECT count(*) FROM auth_users")) == 0
            transaction.rollback()
    finally:
        engine.dispose()
