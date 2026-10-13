from __future__ import annotations

import hashlib
import re

import pytest

from app.rag.chunking import (
    ChunkingConfig,
    HeuristicTokenCounter,
    build_document_chunks,
    group_sections,
    make_chunk_id,
    merge_small_chunks,
    split_section_text,
)
from app.rag.models import DocumentNode, SectionNode

CHUNK_ID_PATTERN = re.compile(r"^CHUNK-[0-9A-F]+-P\d+-\d+-\d{4,}-[0-9A-F]{10}$")


def make_sections(levels_and_text: list[tuple[int, str, str]]) -> list[SectionNode]:
    sections: list[SectionNode] = []
    for ordinal, (level, heading, text) in enumerate(levels_and_text, start=1):
        sections.append(
            SectionNode(
                document_id="DOC-TEST",
                section_ordinal=ordinal,
                heading_path=[heading],
                chapter=heading if level == 1 else None,
                level=level,
                page_start=ordinal,
                page_end=ordinal,
                text=text,
                page_spans=[(0, len(text), ordinal)],
                heading_method="chapter_heading" if level == 1 else "numbered_heading",
            )
        )
    return sections


def make_long_text(words: int = 900) -> str:
    sentence = "The operator should verify the coolant level before starting the spindle again. "
    return (sentence * (words // 12 + 1))[: words * 6]


def test_chunking_config_rejects_invalid_token_bounds() -> None:
    with pytest.raises(ValueError):
        ChunkingConfig(target_tokens=0)
    with pytest.raises(ValueError):
        ChunkingConfig(target_tokens=448, overlap_tokens=448)
    with pytest.raises(ValueError):
        ChunkingConfig(target_tokens=448, overlap_tokens=-1)
    with pytest.raises(ValueError):
        ChunkingConfig(target_tokens=600, max_tokens=500)


def test_chunk_id_is_deterministic_and_well_formed() -> None:
    first = make_chunk_id("DOC-ABC123", 5, 7, 2001, "Chapter 1 > A", "hash-a")
    second = make_chunk_id("DOC-ABC123", 5, 7, 2001, "Chapter 1 > A", "hash-a")
    changed = make_chunk_id("DOC-ABC123", 5, 7, 2001, "Chapter 1 > A", "hash-b")

    assert first == second
    assert first != changed
    assert first.startswith("CHUNK-ABC123-P5-7-2001-")
    assert CHUNK_ID_PATTERN.match(first)


def test_split_section_text_keeps_token_budgets_and_covers_text() -> None:
    config = ChunkingConfig(target_tokens=60, overlap_tokens=10, max_tokens=70, min_tokens=5)
    counter = HeuristicTokenCounter()
    text = make_long_text()
    assert counter.count(text) > config.max_tokens

    ranges = split_section_text(text, config, counter)

    assert len(ranges) > 1
    assert ranges[0][0] == 0
    assert ranges[-1][1] == len(text)
    for start, end in ranges:
        assert start < end
        assert counter.count(text[start:end]) <= config.max_tokens
    for (_, end), (next_start, _) in zip(ranges, ranges[1:]):
        assert next_start < end
    assert ranges == split_section_text(text, config, counter)


def test_split_section_text_returns_single_range_for_short_text() -> None:
    config = ChunkingConfig(target_tokens=60, overlap_tokens=10, max_tokens=70, min_tokens=5)
    counter = HeuristicTokenCounter()
    text = "Short section body."

    assert split_section_text(text, config, counter) == [(0, len(text))]
    assert split_section_text("   ", config, counter) == []


def test_group_sections_never_starts_a_group_with_a_level_one_section() -> None:
    config = ChunkingConfig(target_tokens=10, overlap_tokens=1, max_tokens=20, min_tokens=2)
    counter = HeuristicTokenCounter()
    sections = make_sections(
        [
            (1, "Chapter 1", "chapter one body"),
            (2, "1.1 Alpha", "alpha body"),
            (2, "1.2 Beta", "beta body"),
            (1, "Chapter 2", "chapter two body"),
            (2, "2.1 Gamma", "gamma body"),
        ]
    )

    groups = group_sections(sections, config, counter)

    for group in groups:
        for position, section in enumerate(group[1:], start=1):
            assert not (section.level <= 1 and position > 0)
    assert sum(len(group) for group in groups) == len(sections)


def test_merge_small_chunks_absorbs_undersized_chunk_of_same_document(
    chunk_factory,
) -> None:
    config = ChunkingConfig(target_tokens=100, overlap_tokens=10, max_tokens=120, min_tokens=40)
    counter = HeuristicTokenCounter()
    previous = chunk_factory(
        chunk_id="CHUNK-A-0001-0001-0001-AAAAAAAAAA",
        text="first chunk body " * 4,
        token_count=80,
        page_end=2,
        stable_ordinal=1001,
    )
    small = chunk_factory(
        chunk_id="CHUNK-A-0001-0001-0002-BBBBBBBBBB",
        text="small tail",
        token_count=20,
        page_end=3,
        stable_ordinal=1002,
    )

    merged = merge_small_chunks([previous, small], config, counter)

    assert len(merged) == 1
    assert merged[0].text.endswith("small tail")
    assert merged[0].page_end == 3
    assert merged[0].token_count == counter.count(merged[0].text)
    assert merged[0].chunk_id != previous.chunk_id
    assert merged[0].content_hash == hashlib.sha256(merged[0].text.encode("utf-8")).hexdigest()


def test_merge_small_chunks_skips_when_budget_or_document_differs(chunk_factory) -> None:
    config = ChunkingConfig(target_tokens=100, overlap_tokens=10, max_tokens=120, min_tokens=40)
    counter = HeuristicTokenCounter()
    large = chunk_factory(text="large body " * 6, token_count=110, stable_ordinal=1001)
    small = chunk_factory(text="small tail", token_count=20, stable_ordinal=1002)
    other_document = chunk_factory(
        document_id="DOC-OTHER",
        text="other document tail",
        token_count=20,
        stable_ordinal=1003,
    )

    over_budget = merge_small_chunks([large, small], config, counter)
    assert len(over_budget) == 2

    across_documents = merge_small_chunks(
        [
            chunk_factory(text="body", token_count=10, stable_ordinal=1001),
            other_document,
        ],
        config,
        counter,
    )
    assert len(across_documents) == 2


def test_build_document_chunks_is_deterministic_for_identical_input() -> None:
    config = ChunkingConfig(target_tokens=80, overlap_tokens=15, max_tokens=100, min_tokens=20)
    counter = HeuristicTokenCounter()
    document = DocumentNode(
        document_id="DOC-DETERMINISM",
        filename="doc.pdf",
        relative_path="datasets/raw/doc.pdf",
        document_type="SAFETY",
        sha256="abc",
    )
    sections = make_sections(
        [
            (1, "Chapter 1", make_long_text(120)),
            (2, "1.1 Alpha", make_long_text(60)),
        ]
    )

    first = build_document_chunks(
        document,
        sections,
        config,
        counter,
        embedding_model="test-model",
        ingestion_version="step06.v1",
    )
    second = build_document_chunks(
        document,
        sections,
        config,
        counter,
        embedding_model="test-model",
        ingestion_version="step06.v1",
    )

    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]
    assert [chunk.content_hash for chunk in first] == [chunk.content_hash for chunk in second]
    assert len({chunk.chunk_id for chunk in first}) == len(first)


def test_real_chunk_artifact_invariants(settings, chunks) -> None:
    assert chunks

    ids = [chunk.chunk_id for chunk in chunks]
    assert len(set(ids)) == len(ids)
    assert all(CHUNK_ID_PATTERN.match(chunk_id) for chunk_id in ids)

    for chunk in chunks:
        assert chunk.text.strip()
        assert chunk.page_start <= chunk.page_end
        assert chunk.token_count <= settings.rag_chunk_max_tokens
        assert hashlib.sha256(chunk.text.encode("utf-8")).hexdigest() == chunk.content_hash
        heading_key = " > ".join(chunk.heading_path) if chunk.heading_path else "prelude"
        assert (
            make_chunk_id(
                chunk.document_id,
                chunk.page_start,
                chunk.page_end,
                chunk.stable_ordinal,
                heading_key,
                chunk.content_hash,
            )
            == chunk.chunk_id
        )
        if not chunk.heading_path:
            assert chunk.section_key.endswith("::prelude")

    assert any(chunk.heading_path for chunk in chunks)
    assert any(not chunk.heading_path for chunk in chunks)
    assert all(chunk.source_type in {"MANUAL", "SAFETY", "SOP"} for chunk in chunks)
