"""A lazily loaded, CPU-only Sentence Transformers encoder."""

import hashlib
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Protocol

import numpy as np

from fleetmind.observability import timed

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_REVISION = "c9745ed1d9f207416be6d2e6f8de32d1f16199bf"
logger = logging.getLogger(__name__)


class EmbeddingUnavailable(RuntimeError):
    pass


class EmbeddingInputError(ValueError):
    pass


@dataclass(frozen=True)
class EmbeddingIdentity:
    name: str
    revision: str
    dimensions: int

    @property
    def key(self) -> str:
        key = f"{self.name}\0{self.revision}\0{self.dimensions}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()


class Embedder(Protocol):
    @property
    def identity(self) -> EmbeddingIdentity: ...

    def encode(self, inputs: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class EmbeddingSettings:
    name: str
    revision: str | None
    directory: Path | None
    offline: bool
    profile: str | None = None

    @classmethod
    def from_environment(cls):
        name = os.getenv("FLEETMIND_EMBEDDING_MODEL", DEFAULT_MODEL)
        directory = os.getenv("FLEETMIND_EMBEDDING_DIRECTORY")
        revision = os.getenv("FLEETMIND_EMBEDDING_REVISION")
        profile = os.getenv("FLEETMIND_EMBEDDING_PROFILE")
        if profile and not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", profile):
            raise EmbeddingUnavailable(
                "Use a short lowercase embedding profile identifier."
            )
        if not directory and name == DEFAULT_MODEL:
            revision = revision or DEFAULT_REVISION
        if len(name) > 160 or not re.fullmatch(r"[\w.-]+(?:/[\w.-]+)?", name):
            raise EmbeddingUnavailable("Configure a logical embedding model name.")
        if not directory and (
            not revision or not re.fullmatch(r"[a-f0-9]{40}", revision)
        ):
            raise EmbeddingUnavailable("Configure a full remote model commit revision.")
        if revision and (len(revision) > 128 or not re.fullmatch(r"[\w.-]+", revision)):
            raise EmbeddingUnavailable("Configure a valid embedding model revision.")
        return cls(
            name,
            revision,
            Path(directory) if directory else None,
            os.getenv("FLEETMIND_EMBEDDING_OFFLINE", "1") != "0",
            profile,
        )


def local_revision(directory: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(
        item
        for item in directory.rglob("*")
        if item.is_file() and item.suffix in {".safetensors", ".json", ".txt", ".model"}
    )
    if not any(item.suffix == ".safetensors" for item in files):
        raise EmbeddingUnavailable(
            "The local embedding model needs safetensors weights."
        )
    for file in files:
        digest.update(file.relative_to(directory).as_posix().encode("utf-8"))
        digest.update(b"\0")
        with file.open("rb") as stream:
            digest.update(hashlib.file_digest(stream, "sha256").digest())
    return f"sha256-{digest.hexdigest()}"


class SentenceEmbedder:
    def __init__(self, *, batch_size: int = 16):
        if not 1 <= batch_size <= 64:
            raise ValueError("Embedding batch size must be between 1 and 64.")
        self.batch_size = batch_size
        self.lock = Lock()
        self.model = None
        self._identity: EmbeddingIdentity | None = None
        self.initialization_state = "cold"

    @property
    def loaded_identity(self) -> EmbeddingIdentity | None:
        return self._identity

    @property
    def identity(self) -> EmbeddingIdentity:
        with self.lock:
            if self._identity is None:
                self._initialize()
            assert self._identity is not None
            return self._identity

    def prewarm_offline(self) -> None:
        with self.lock:
            if self._identity is None:
                try:
                    self._initialize(force_offline=True)
                except EmbeddingUnavailable:
                    logger.warning("Cached embedding prewarm unavailable")

    @timed("embedding_load", log=True)
    def _initialize(self, *, force_offline: bool = False) -> None:
        self.initialization_state = "initializing"
        try:
            self._load(force_offline=force_offline)
        except EmbeddingUnavailable:
            self.initialization_state = "unavailable"
            raise
        self.initialization_state = "ready"

    def _load(self, *, force_offline: bool = False) -> None:
        settings = EmbeddingSettings.from_environment()
        try:
            from sentence_transformers import SentenceTransformer

            if settings.directory is not None and not settings.directory.is_dir():
                raise EmbeddingUnavailable(
                    "The configured embedding directory is missing."
                )
            revision = settings.revision
            if settings.directory is not None and not revision:
                revision = local_revision(settings.directory)
            model = SentenceTransformer(
                str(settings.directory)
                if settings.directory is not None
                else settings.name,
                revision=None if settings.directory is not None else revision,
                local_files_only=force_offline
                or settings.offline
                or settings.directory is not None,
                device="cpu",
                trust_remote_code=False,
                model_kwargs={"use_safetensors": True},
            )
            dimension_reader = getattr(model, "get_embedding_dimension", None)
            dimensions = (
                dimension_reader()
                if dimension_reader
                else model.get_sentence_embedding_dimension()
            )
            if dimensions is None or not 1 <= dimensions <= 2000:
                raise EmbeddingUnavailable(
                    "Expected an embedding model with 1–2000 dimensions."
                )
            assert revision is not None
        except EmbeddingUnavailable:
            raise
        except Exception as exc:
            logger.warning("Embedding initialization failed (%s)", type(exc).__name__)
            raise EmbeddingUnavailable(
                "The embedding model is unavailable. Install the optional dependencies "
                "and cache the configured model revision or supply a local copy."
            ) from exc
        indexed_revision = (
            f"{revision}+{settings.profile}" if settings.profile else revision
        )
        if len(indexed_revision) > 128:
            raise EmbeddingUnavailable("The configured embedding identity is too long.")
        self.model = model
        self._identity = EmbeddingIdentity(settings.name, indexed_revision, dimensions)

    @timed("embedding_encode")
    def encode(self, inputs: list[str]) -> list[list[float]]:
        if not inputs:
            return []
        identity = self.identity
        with self.lock:
            assert self.model is not None
            results = []
            for start in range(0, len(inputs), self.batch_size):
                batch = inputs[start : start + self.batch_size]
                tokens = self.model.tokenizer(batch, truncation=False, verbose=False)
                if any(
                    len(ids) > self.model.max_seq_length for ids in tokens["input_ids"]
                ):
                    raise EmbeddingInputError(
                        "Text exceeds the embedding token limit. Shorten the query or "
                        "reduce the document chunk size."
                    )
                try:
                    vectors = np.asarray(
                        self.model.encode(
                            batch,
                            batch_size=self.batch_size,
                            normalize_embeddings=True,
                            show_progress_bar=False,
                            convert_to_numpy=True,
                        )
                    )
                except (RuntimeError, OSError) as exc:
                    raise EmbeddingUnavailable("Embedding generation failed.") from exc
                if (
                    vectors.shape != (len(batch), identity.dimensions)
                    or not np.isfinite(vectors).all()
                    or np.any(np.linalg.norm(vectors, axis=1) == 0)
                ):
                    raise EmbeddingUnavailable(
                        "The model returned invalid embedding vectors."
                    )
                results.extend(vectors.tolist())
        return results


_embedder = SentenceEmbedder()


def get_embedder() -> SentenceEmbedder:
    return _embedder
