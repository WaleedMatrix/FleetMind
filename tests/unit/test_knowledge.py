from math import isclose

import pytest

from fleetmind.knowledge.documents import chunk_document, normalize, read_document
from fleetmind.knowledge.embeddings import (
    DEFAULT_MODEL,
    DEFAULT_REVISION,
    EmbeddingSettings,
    EmbeddingUnavailable,
    local_revision,
)
from fleetmind.knowledge.retrieval import reciprocal_rank_fusion
from fleetmind.knowledge.schemas import DocumentInput, SearchRequest


def test_normalization_and_headings_preserve_stable_ids():
    original = "# Manual\r\n\r\n## Review\r\nverify recorded sensor units  \r\n"
    chunks = chunk_document("manual", original, "Review guide", "markdown")
    assert chunks[0].section == "Manual / Review"
    assert chunks[0].content == "verify recorded sensor units"
    updated = chunk_document(
        "manual",
        "Initial remarks\n\n" + normalize(original),
        "Review guide",
        "markdown",
    )
    assert updated[1].id == chunks[0].id
    assert updated[1].position == 1
    assert updated[1].input_hash == chunks[0].input_hash
    assert updated[1].content_hash == chunks[0].content_hash


def test_chunks_do_not_cross_sections_or_add_a_redundant_tail():
    body = "# A\none two three four five six\n# B\nseven eight"
    chunks = chunk_document("source", body, "Title", "markdown", size=4, overlap=2)
    assert [(chunk.section, chunk.content) for chunk in chunks] == [
        ("A", "one two three four"),
        ("A", "three four five six"),
        ("B", "seven eight"),
    ]
    fenced = chunk_document(
        "source", "# A\n```\n# comment\n```\nend", "Title", "markdown"
    )
    assert len(fenced) == 1 and "# comment" in fenced[0].content
    with pytest.raises(ValueError, match="overlap"):
        chunk_document("source", body, "Title", "markdown", size=2, overlap=2)
    with pytest.raises(ValueError, match="no text"):
        chunk_document("source", "# Empty", "Title", "markdown")


def test_plain_text_reads_utf8_bom_and_rejects_unknown_file_type(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("Field observation", encoding="utf-8-sig")
    body, format = read_document(path)
    assert (body, format) == ("Field observation", "text")
    assert chunk_document("notes", body, "Notes", format)[0].section == "Notes"
    with pytest.raises(ValueError, match="Markdown"):
        read_document(path.with_suffix(".pdf"))


def test_rank_fusion_rewards_agreement_and_resolves_ties_by_id():
    fused = reciprocal_rank_fusion(["b", "c", "a"], ["a", "c", "b"], constant=60)
    assert [item[0] for item in fused] == ["a", "b", "c"]
    assert isclose(fused[0][1], 1 / 61 + 1 / 63)
    assert reciprocal_rank_fusion(["a", "a"], ["b"])[0][0] == "a"
    assert [row[0] for row in reciprocal_rank_fusion(["a", "b"], ["b"])] == ["b", "a"]
    assert reciprocal_rank_fusion([], []) == []


def test_query_and_public_source_reference_validation():
    assert SearchRequest(query="  torque  ").query == "torque"
    for value in ("\0", "x" * 513, " "):
        with pytest.raises(ValueError):
            SearchRequest(query=value)
    for path in ("C:/data/private.txt", "/etc/private", "../hidden", "docs/../hidden"):
        with pytest.raises(ValueError):
            DocumentInput(
                id="test",
                title="Test",
                category="project",
                source_kind="project",
                source_ref=path,
            )


def test_offline_defaults_and_local_revisions(monkeypatch, tmp_path):
    for suffix in ("MODEL", "DIRECTORY", "REVISION", "OFFLINE"):
        monkeypatch.delenv(f"FLEETMIND_EMBEDDING_{suffix}", raising=False)
    settings = EmbeddingSettings.from_environment()
    assert settings.name == DEFAULT_MODEL and settings.revision == DEFAULT_REVISION
    assert settings.offline
    monkeypatch.setenv("FLEETMIND_EMBEDDING_MODEL", "other/model")
    with pytest.raises(EmbeddingUnavailable, match="commit"):
        EmbeddingSettings.from_environment()
    with pytest.raises(EmbeddingUnavailable, match="safetensors"):
        local_revision(tmp_path)
    weights = tmp_path / "model.safetensors"
    weights.write_bytes(b"fixture")
    revision = local_revision(tmp_path)
    weights.write_bytes(b"updated fixture")
    assert local_revision(tmp_path) != revision
