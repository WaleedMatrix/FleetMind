"""Normalize and chunk Markdown and plain-text sources with stable references."""

import hashlib
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

MAX_BYTES = 1024 * 1024
MAX_CHUNKS = 2000
DocumentFormat = Literal["markdown", "text"]
_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.+?)\s*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_document(path: Path) -> tuple[str, DocumentFormat]:
    ext = path.suffix.lower()
    if ext not in {".md", ".markdown", ".txt"}:
        raise ValueError("Documents must be Markdown (.md, .markdown) or text (.txt).")
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Documents must be at most 1 MiB.")
    return raw.decode("utf-8-sig"), ("text" if ext == ".txt" else "markdown")


def normalize(text: str) -> str:
    if "\0" in text:
        raise ValueError("Documents cannot contain NUL characters.")
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    return "\n".join(line.rstrip() for line in text.split("\n")).strip("\n ")


def sections(text: str, title: str, format: DocumentFormat):
    if format == "text":
        yield title, text
        return

    parents: list[tuple[int, str]] = []
    buffer: list[str] = []
    fence: str | None = None
    for line in text.splitlines():
        marker = _FENCE.match(line)
        if marker:
            match, rest = marker.groups()
            if fence is None:
                fence = match
            elif match[0] == fence[0] and len(match) >= len(fence) and not rest.strip():
                fence = None
        heading = _HEADING.match(line) if fence is None else None
        if heading:
            if buffer:
                yield (
                    " / ".join(name for _, name in parents) or title,
                    "\n".join(buffer),
                )
                buffer = []
            level = len(heading[1])
            parents = [(depth, name) for depth, name in parents if depth < level]
            name = re.sub(r"\s+#+$", "", heading[2]).strip()
            parents.append((level, name))
        else:
            buffer.append(line)
    if buffer:
        yield " / ".join(name for _, name in parents) or title, "\n".join(buffer)


@dataclass(frozen=True)
class ChunkDraft:
    id: str
    position: int
    section: str
    content: str
    content_hash: str
    input_hash: str

    @property
    def embedding_input(self) -> str:
        return f"{self.section}\n{self.content}"


def chunk_document(
    document_id: str,
    text: str,
    title: str,
    format: DocumentFormat,
    size: int = 100,
    overlap: int = 15,
) -> list[ChunkDraft]:
    if not 1 <= size <= 512 or not 0 <= overlap < size:
        raise ValueError("Chunk size must be 1–512 words with a smaller overlap.")
    drafts = []
    duplicates: Counter[str] = Counter()
    for name, body in sections(normalize(text), title, format):
        words = body.split()
        for start in range(0, len(words), size - overlap):
            content = " ".join(words[start : start + size])
            input_hash = sha256(f"{name}\n{content}")
            occurrence = duplicates[input_hash]
            duplicates[input_hash] += 1
            drafts.append(
                ChunkDraft(
                    id=sha256(f"{document_id}\0{input_hash}\0{occurrence}"),
                    position=len(drafts),
                    section=name,
                    content=content,
                    content_hash=sha256(content),
                    input_hash=input_hash,
                )
            )
            if len(drafts) > MAX_CHUNKS:
                raise ValueError("Document exceeds the 2,000 chunk limit.")
            if start + size >= len(words):
                break
    if not drafts:
        raise ValueError("Document contains no text to index.")
    return drafts
