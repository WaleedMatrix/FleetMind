"""Check real pgvector, generated FTS, and additive migrations on PostgreSQL."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fleetmind.api.main import app
from fleetmind.db.database import get_db
from fleetmind.knowledge.embeddings import (
    EmbeddingIdentity,
    EmbeddingUnavailable,
    get_embedder,
)
from fleetmind.knowledge.ingestion import ingest, remove
from fleetmind.knowledge.models import Chunk, ChunkEmbedding, Document, IngestionEvent
from fleetmind.knowledge.retrieval import search
from fleetmind.knowledge.schemas import DocumentInput, SearchRequest, SearchResponse

TEST_URL = os.environ.get("FLEETMIND_MIGRATION_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not TEST_URL, reason="Requires disposable PostgreSQL + pgvector"
)
CONFIG = Path(__file__).resolve().parents[2] / "alembic.ini"


class TestEncoder:
    __test__ = False
    identity = EmbeddingIdentity("fleetmind-test/fixture", "v1", 3)
    loaded_identity = identity

    def __init__(self):
        self.encoded = []

    def encode(self, values):
        self.encoded.extend(values)
        return [
            [1.0, 0.0, 0.0] if "torque" in value.lower() else [0.0, 1.0, 0.0]
            for value in values
        ]


class OfflineEncoder:
    loaded_identity = None

    @property
    def identity(self):
        raise EmbeddingUnavailable("Embedding fixture unavailable.")


def spec(id, **fields):
    return DocumentInput.model_validate(
        {
            "id": id,
            "title": id.title(),
            "category": "sensors",
            "source_kind": "project",
            "source_ref": f"docs/{id}.md",
            **fields,
        }
    )


@pytest.fixture
def store():
    engine = create_engine(TEST_URL)
    schema = f"fleetmind_knowledge_test_{uuid4().hex}"
    try:
        assert engine.dialect.name == "postgresql"
        with engine.connect() as connection, connection.begin() as transaction:
            connection.execute(text(f"CREATE SCHEMA {schema}"))
            connection.execute(text(f"SET LOCAL search_path TO {schema}"))
            config = Config(CONFIG)
            config.attributes["connection"] = connection
            command.upgrade(config, "0002_asset_intelligence")
            connection.execute(
                text(
                    "INSERT INTO assets (asset_id, display_name, machine_type) "
                    "VALUES ('fixture', 'Preserved machine', 'L')"
                )
            )
            connection.execute(
                text("""
                INSERT INTO prediction_history (
                    machine_type, air_temperature_k, process_temperature_k,
                    rotational_speed_rpm, torque_nm, tool_wear_min, failure_score,
                    predicted_failure, alert_level, model_version, created_at, asset_id
                ) VALUES ('L', 300, 310, 1500, 42, 120, 0.5, true, 'review',
                          'fixture', CURRENT_TIMESTAMP, 'fixture')
            """)
            )
            before = connection.execute(text("SELECT * FROM prediction_history")).all()
            connection.execute(text(f"SET LOCAL search_path TO {schema}, public"))
            command.upgrade(config, "head")
            command.upgrade(config, "head")
            assert (
                connection.execute(text("SELECT * FROM prediction_history")).all()
                == before
            )
            assert {"ix_kchunk_search"} <= {
                item["name"]
                for item in inspect(connection).get_indexes(
                    "knowledge_chunks", schema=schema
                )
            }
            yield connection
            transaction.rollback()
    finally:
        engine.dispose()


def test_ingestion_reuses_stable_chunks_and_records_updates(store):
    encoder = TestEncoder()
    with Session(store, join_transaction_mode="create_savepoint") as db, db.begin():
        doc = spec("sensor")
        original = "# Signals\n## Torque\nTorque units.\n## Speed\nRPM units."
        assert ingest(db, doc, original, "markdown", encoder).generated == 2
        stable = db.scalar(select(Chunk.id).where(Chunk.section.like("%Torque")))
        unchanged = ingest(db, doc, original.replace("\n", "\r\n"), "markdown", encoder)
        assert (unchanged.action, unchanged.generated) == ("unchanged", 0)
        assert db.scalar(select(func.count()).select_from(IngestionEvent)) == 1
        with pytest.raises(ValueError, match="Duplicate normalized content"):
            ingest(db, spec("copy"), original, "markdown", encoder)
        revised = original.replace(
            "RPM units.", "Speed expressed in revolutions per minute."
        )
        updated = ingest(db, doc, revised, "markdown", encoder)
        assert (updated.action, updated.generated, updated.reused) == ("updated", 1, 1)
        assert db.get(Chunk, stable) is not None
        assert len(encoder.encoded) == 3
        with pytest.raises(IntegrityError), db.begin_nested():
            db.execute(text("UPDATE knowledge_embeddings SET dimensions = 4"))
        assert remove(db, doc.id)
    with Session(store) as db:
        assert db.get(Document, "sensor") is None
        assert db.scalar(select(func.count()).select_from(ChunkEmbedding)) == 0
        assert db.scalar(select(func.count()).select_from(IngestionEvent)) == 3


def test_retrieval_ranks_real_database_results_and_preserves_citations(store):
    encoder = TestEncoder()
    with Session(store, join_transaction_mode="create_savepoint") as db, db.begin():
        for identifier, body in [
            ("torque", "# Torque\nTorque uses newton metres."),
            ("speed", "# Speed\nSpeed uses revolutions per minute."),
        ]:
            ingest(db, spec(identifier), body, "markdown", encoder)
        for mode in ("semantic", "keyword", "hybrid"):
            result = search(db, SearchRequest(query="torque", mode=mode), encoder)
            hit = result.results[0]
            assert result.diagnostics.used_mode == mode
            assert hit.citation.document_id == "torque"
            assert hit.citation.source_ref == "docs/torque.md"
            assert hit.citation.section == "Torque"
            assert hit.citation.chunk_id == db.get(Chunk, hit.citation.chunk_id).id
            assert hit.content == "Torque uses newton metres."
        hybrid = search(db, SearchRequest(query="torque"), encoder)
        assert hybrid.results[0].rrf_score == pytest.approx(2 / 61)
        assert hybrid.results[0].semantic_similarity == pytest.approx(1.0)
        assert hybrid.results[0].keyword_rank == 1
        fallback = search(db, SearchRequest(query="torque"), OfflineEncoder())
        assert fallback.diagnostics.fallback == "embedding_unavailable"
        assert fallback.diagnostics.used_mode == "keyword"
        filtered = search(
            db,
            SearchRequest(
                query="torque",
                filters={"source_ref": "docs/speed.md"},
            ),
            encoder,
        )
        assert [hit.citation.document_id for hit in filtered.results] == ["speed"]


def test_knowledge_api_validates_queries_and_supports_empty_and_offline(store):
    encoder = TestEncoder()

    def db_session():
        with Session(store, join_transaction_mode="create_savepoint") as db:
            yield db

    app.dependency_overrides[get_db] = db_session
    app.dependency_overrides[get_embedder] = OfflineEncoder
    try:
        with TestClient(app) as client:
            assert client.get("/api/v1/knowledge/status").json()["state"] == "empty"
            base = "/api/v1/knowledge"
            empty = client.post(
                f"{base}/search", json={"query": "torque", "mode": "semantic"}
            )
            assert empty.status_code == 200 and empty.json()["results"] == []
            with (
                Session(store, join_transaction_mode="create_savepoint") as db,
                db.begin(),
            ):
                ingest(
                    db, spec("torque"), "Torque uses newton metres.", "text", encoder
                )
            status = client.get(f"{base}/status").json()
            assert status["indexed_profiles"][0]["dimensions"] == 3
            assert status["indexed_profiles"][0]["revision"] == "v1"
            assert client.get(f"{base}/documents").json()[0]["id"] == "torque"
            detail = client.get(f"{base}/documents/torque").json()
            assert detail["chunk_count"] == 1
            chunk = detail["chunks"][0]
            assert (
                client.get(f"{base}/documents/torque/chunks/{chunk['id']}").json()
                == chunk
            )
            assert (
                client.get(f"{base}/documents/other/chunks/{chunk['id']}").status_code
                == 404
            )
            assert (
                client.get(f"{base}/documents/torque/chunks/invalid").status_code == 422
            )
            assert client.get(f"{base}/documents/no-match").status_code == 404
            assert (
                client.post(
                    f"{base}/search", json={"query": "x", "top_k": 21}
                ).status_code
                == 422
            )
            assert (
                client.post(
                    f"{base}/search", json={"query": "torque", "mode": "semantic"}
                ).status_code
                == 503
            )
            body = SearchResponse.model_validate(
                client.post(f"{base}/search", json={"query": "torque"}).json()
            )
            assert body.results[0].citation.chunk_id == detail["chunks"][0]["id"]
            assert body.diagnostics.used_mode == "keyword"
    finally:
        app.dependency_overrides.clear()
