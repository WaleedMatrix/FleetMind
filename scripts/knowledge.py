"""Manage trusted local sources in the FleetMind knowledge store."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from fleetmind.db.database import SessionLocal
from fleetmind.knowledge.documents import read_document
from fleetmind.knowledge.embeddings import EmbeddingUnavailable, SentenceEmbedder
from fleetmind.knowledge.ingestion import ingest, remove
from fleetmind.knowledge.models import Chunk, Document, IngestionEvent
from fleetmind.knowledge.schemas import ChunkInfo, DocumentInfo, DocumentInput

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "docs" / "knowledge"


def chunk_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--chunk-size", type=int, default=100, help="Words per section chunk"
    )
    parser.add_argument(
        "--overlap", type=int, default=15, help="Words shared by adjacent chunks"
    )
    parser.add_argument(
        "--batch-size", type=int, default=16, help="Embedding batch size"
    )


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest="command", required=True)
    add = sub.add_parser("ingest", help="Add or update a Markdown or text source")
    add.add_argument("file", type=Path)
    add.add_argument("--id", required=True)
    add.add_argument("--title", required=True)
    add.add_argument("--category", required=True)
    add.add_argument("--source-kind", default="reference")
    add.add_argument(
        "--source-ref", help="Public logical reference. Defaults to the file name."
    )
    chunk_options(add)
    seed = sub.add_parser("seed", help="Ingest the checked-in FleetMind starter corpus")
    chunk_options(seed)
    sub.add_parser(
        "prefetch", help="Validate availability of the configured embedding model"
    )
    listing = sub.add_parser("list", help="List documents")
    listing.add_argument("--limit", type=int, default=20)
    listing.add_argument("--offset", type=int, default=0)
    for command in ("inspect", "events", "remove"):
        command_parser = sub.add_parser(command)
        command_parser.add_argument("id")
    return cli


def emit(value) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str))


def source_entries(args):
    if args.command == "ingest":
        yield (
            args.file,
            DocumentInput(
                id=args.id,
                title=args.title,
                category=args.category,
                source_kind=args.source_kind,
                source_ref=args.source_ref or args.file.name,
            ),
        )
        return
    entries = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    for entry in entries:
        file = (CORPUS / entry["file"]).resolve()
        if not file.is_relative_to(CORPUS.resolve()):
            raise ValueError(
                "Starter document path must be inside the corpus directory."
            )
        yield (
            file,
            DocumentInput.model_validate(
                {field: value for field, value in entry.items() if field != "file"}
            ),
        )


def index_sources(args) -> None:
    started = perf_counter()
    embedder = SentenceEmbedder(batch_size=args.batch_size)
    with SessionLocal.begin() as db:
        results = []
        for file, spec in source_entries(args):
            body, format = read_document(file)
            results.append(
                asdict(
                    ingest(
                        db,
                        spec,
                        body,
                        format,
                        embedder,
                        chunk_size=args.chunk_size,
                        chunk_overlap=args.overlap,
                    )
                )
            )
    emit(
        {
            "profile": asdict(embedder.identity),
            "total_ms_including_commit": (perf_counter() - started) * 1000,
            "documents": results,
        }
    )


def inspect_store(args) -> None:
    with SessionLocal.begin() as db:
        if args.command == "list":
            if not 1 <= args.limit <= 100 or args.offset < 0:
                raise ValueError("Limit must be 1–100 and offset must be nonnegative.")
            query = (
                select(Document)
                .order_by(Document.id)
                .limit(args.limit)
                .offset(args.offset)
            )
            emit(
                [
                    DocumentInfo.model_validate(row).model_dump(mode="json")
                    for row in db.scalars(query)
                ]
            )
        elif args.command == "remove":
            if not remove(db, args.id):
                raise ValueError("Knowledge document not found.")
        elif args.command == "events":
            rows = db.scalars(
                select(IngestionEvent)
                .where(
                    IngestionEvent.document_id == args.id,
                )
                .order_by(IngestionEvent.id.desc())
                .limit(20)
            )
            emit(
                [
                    {
                        "action": row.action,
                        "content_hash": row.content_hash,
                        "model_key": row.model_key,
                        "chunks": row.chunk_count,
                        "generated": row.generated,
                        "reused": row.reused,
                        "elapsed_ms": row.elapsed_ms,
                        "created_at": row.created_at,
                    }
                    for row in rows
                ]
            )
        else:
            document = db.get(Document, args.id)
            if document is None:
                raise ValueError("Knowledge document not found.")
            chunks = db.scalars(
                select(Chunk)
                .where(Chunk.document_id == args.id)
                .order_by(Chunk.position)
            )
            emit(
                {
                    "document": DocumentInfo.model_validate(document).model_dump(
                        mode="json"
                    ),
                    "chunks": [
                        ChunkInfo.model_validate(row).model_dump(mode="json")
                        for row in chunks
                    ],
                }
            )
    if args.command == "remove":
        emit({"removed": args.id})


def main() -> None:
    cli = parser()
    args = cli.parse_args()
    try:
        if args.command == "prefetch":
            emit(asdict(SentenceEmbedder().identity))
        elif args.command in {"ingest", "seed"}:
            index_sources(args)
        else:
            inspect_store(args)
    except (EmbeddingUnavailable, ValueError, OSError) as exc:
        cli.exit(1, f"Knowledge operation failed: {exc}\n")
    except SQLAlchemyError:
        cli.exit(
            1,
            "Knowledge database unavailable or rejected the operation. "
            "Check migrations.\n",
        )


if __name__ == "__main__":
    main()
