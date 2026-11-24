"""Exercise the PostgreSQL migrations in isolated development schemas."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

TEST_URL = os.environ.get("FLEETMIND_MIGRATION_TEST_DATABASE_URL")
CONFIG = Path(__file__).resolve().parents[2] / "alembic.ini"

LEGACY_DDL = """
CREATE TABLE prediction_history (
    id SERIAL PRIMARY KEY,
    machine_type VARCHAR(1) NOT NULL,
    air_temperature_k DOUBLE PRECISION NOT NULL,
    process_temperature_k DOUBLE PRECISION NOT NULL,
    rotational_speed_rpm DOUBLE PRECISION NOT NULL,
    torque_nm DOUBLE PRECISION NOT NULL,
    tool_wear_min DOUBLE PRECISION NOT NULL,
    failure_score DOUBLE PRECISION NOT NULL,
    predicted_failure BOOLEAN NOT NULL,
    alert_level VARCHAR(20) NOT NULL,
    model_version VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
)
"""
INSERT_READING = """
INSERT INTO prediction_history (
    machine_type, air_temperature_k, process_temperature_k, rotational_speed_rpm,
    torque_nm, tool_wear_min, failure_score, predicted_failure, alert_level,
    model_version, created_at {asset_column}
) VALUES (
    'M', 299.5, 310, 1800, 42.75, 125, 0.21, false, 'no_alert',
    'legacy-fixture', '2026-01-06T12:00:00Z' {asset_value}
) RETURNING id
"""


@pytest.mark.skipif(not TEST_URL, reason="Requires an isolated PostgreSQL dev database")
@pytest.mark.parametrize("has_legacy_table", [False, True], ids=["fresh", "legacy"])
def test_asset_migration(has_legacy_table):
    schema = f"fleetmind_migration_test_{uuid4().hex}"
    engine = create_engine(TEST_URL)
    try:
        assert engine.dialect.name == "postgresql"
        with engine.connect() as connection, connection.begin():
            connection.execute(text(f"CREATE SCHEMA {schema}"))
            connection.execute(text(f"SET LOCAL search_path TO {schema}"))
            if has_legacy_table:
                connection.execute(text(LEGACY_DDL))
                legacy = connection.execute(
                    text(INSERT_READING.format(asset_column="", asset_value=""))
                ).scalar_one()
                original = (
                    connection.execute(
                        text("SELECT * FROM prediction_history WHERE id = :id"),
                        {"id": legacy},
                    )
                    .mappings()
                    .one()
                )

            config = Config(CONFIG)
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            command.upgrade(config, "head")

            assert {"assets", "prediction_history"} <= set(
                inspect(connection).get_table_names(schema=schema)
            )
            indexes = inspect(connection).get_indexes(
                "prediction_history", schema=schema
            )
            assert {index["name"] for index in indexes} >= {
                "ix_prediction_history_asset_id_id",
                "ix_prediction_history_asset_alert_id",
            }
            if has_legacy_table:
                upgraded = dict(
                    connection.execute(
                        text("SELECT * FROM prediction_history WHERE id = :id"),
                        {"id": legacy},
                    )
                    .mappings()
                    .one()
                )
                assert upgraded.pop("asset_id") is None
                assert upgraded.pop("source") == "unknown"
                assert upgraded == dict(original)

            connection.execute(
                text(
                    "INSERT INTO assets (asset_id, display_name, machine_type) "
                    "VALUES ('press-test', 'Test press', 'M')"
                )
            )
            associated = text(
                INSERT_READING.format(
                    asset_column=", asset_id", asset_value=", :asset_id"
                )
            )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(associated, {"asset_id": "does-not-exist"})
            reading_id = connection.execute(
                associated, {"asset_id": "press-test"}
            ).scalar_one()
            assert reading_id > (legacy if has_legacy_table else 0)
            # Roll back this test's work, including its isolated schema.
            connection.rollback()
    finally:
        engine.dispose()
