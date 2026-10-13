from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol, Sequence

from .models import ChunkRecord, DocumentNode, SectionNode, map_document_source_type


class TokenCounter(Protocol):
    """Counts approximation-compatible tokens for chunk sizing."""

    name: str

    def count(self, text: str) -> int: ...


@dataclass(slots=True)
class HeuristicTokenCounter:
    """Deterministic fallback counter used when no tokenizer is available."""

    name: str = "heuristic_chars_div_4"

    def count(self, text: str) -> int:
        if not text:
            return 0
        words = len(text.split())
        return max(1, round(max(len(text) / 4.0, words * 1.3)))


@dataclass(slots=True)
class TransformersTokenCounter:
    """Exact token counter backed by the local HuggingFace tokenizer."""

    tokenizer: object
    name: str = "hf_tokenizer"

    @classmethod
    def load(cls, model_name: str) -> "TransformersTokenCounter | None":
        try:
            from transformers import AutoTokenizer
        except Exception:  # pragma: no cover - optional dependency
            return None
        try:
            tokenizer = AutoTokenizer.from_pretrained(model_name)
        except Exception:  # pragma: no cover - offline or corrupt cache
            return None
        # Counting whole sections is intentionally untruncated; silence the
        # "longer than maximum sequence length" warning raised for that case.
        tokenizer.model_max_length = int(10**9)
        return cls(tokenizer=tokenizer, name=f"hf_tokenizer:{model_name}")

    def count(self, text: str) -> int:
        if not text:
            return 0
        encoded = self.tokenizer(text, add_special_tokens=False, truncation=False)
        return len(encoded["input_ids"])


@dataclass(slots=True)
class ChunkingConfig:
    target_tokens: int = 448
    overlap_tokens: int = 80
    max_tokens: int = 500
    min_tokens: int = 120
    paragraph_snap_ratio: float = 0.6
    sentence_snap_ratio: float = 0.7
    char_search_factor: int = 8

    def __post_init__(self) -> None:
        if self.target_tokens <= 0 or self.max_tokens <= 0:
            raise ValueError("chunk token limits must be positive")
        if self.overlap_tokens < 0 or self.overlap_tokens >= self.target_tokens:
            raise ValueError("overlap_tokens must be in [0, target_tokens)")
        if self.target_tokens > self.max_tokens:
            raise ValueError("target_tokens must not exceed max_tokens")


def make_chunk_id(
    document_id: str,
    page_start: int,
    page_end: int,
    ordinal: int,
    heading_key: str,
    content_hash: str,
) -> str:
    """Build a stable, collision-resistant chunk identifier."""

    short_document = document_id.removeprefix("DOC-")
    seed = "|".join(
        [
            document_id,
            str(page_start),
            str(page_end),
            str(ordinal),
            heading_key,
            content_hash,
        ]
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:10].upper()
    return f"CHUNK-{short_document}-P{page_start}-{page_end}-{ordinal:04d}-{digest}"


def _find_window_end(text: str, start: int, config: ChunkingConfig, counter: TokenCounter) -> int:
    """Largest end offset for a window that respects max_tokens, snapped to text boundaries."""

    remaining = text[start:]
    if counter.count(remaining) <= config.max_tokens:
        return len(text)
    low = start + 1
    high = min(len(text), start + config.max_tokens * config.char_search_factor)
    while low < high:
        mid = (low + high + 1) // 2
        if counter.count(text[start:mid]) <= config.max_tokens:
            low = mid
        else:
            high = mid - 1
    end = low
    window = text[start:end]
    paragraph_break = window.rfind("\n\n")
    if paragraph_break != -1 and paragraph_break >= config.paragraph_snap_ratio * len(window):
        return start + paragraph_break
    sentence_break = max(window.rfind(". "), window.rfind("\n"), window.rfind("; "))
    if sentence_break != -1 and sentence_break >= config.sentence_snap_ratio * len(window):
        return start + sentence_break + 1
    return end


def _find_overlap_start(text: str, start: int, end: int, config: ChunkingConfig, counter: TokenCounter) -> int:
    """Smallest offset that keeps at most overlap_tokens of shared tail context."""

    if config.overlap_tokens <= 0:
        return end
    low = start
    high = end
    while low < high:
        mid = (low + high) // 2
        if counter.count(text[mid:end]) <= config.overlap_tokens:
            high = mid
        else:
            low = mid + 1
    candidate = low
    if candidate >= end:
        return end
    if candidate <= start:
        return min(end, start + 1)
    return candidate


def split_section_text(
    text: str,
    config: ChunkingConfig,
    counter: TokenCounter,
) -> list[tuple[int, int]]:
    """Split one section into overlapping token-bounded character ranges."""

    if not text.strip():
        return []
    if counter.count(text) <= config.max_tokens:
        return [(0, len(text))]
    ranges: list[tuple[int, int]] = []
    start = 0
    length = len(text)
    while start < length:
        end = _find_window_end(text, start, config, counter)
        if end <= start:
            end = min(length, start + 1)
        ranges.append((start, end))
        if end >= length:
            break
        next_start = _find_overlap_start(text, start, end, config, counter)
        if next_start <= start:
            next_start = min(end, start + 1)
        start = next_start
    return ranges


def group_sections(
    sections: list[SectionNode],
    config: ChunkingConfig,
    counter: TokenCounter,
) -> list[list[SectionNode]]:
    """Merge small neighbouring sections so chunks reach the target size.

    Groups never cross a chapter boundary (level <= 1 or a detected chapter
    heading), so hierarchy stays meaningful while tiny sections are absorbed.
    """

    groups: list[list[SectionNode]] = []
    current: list[SectionNode] = []
    tokens = 0
    for section in sections:
        section_tokens = counter.count(section.text)
        boundary = bool(current) and (
            section.level <= 1 or section.heading_method == "chapter_heading"
        )
        if current and (tokens >= config.target_tokens or boundary):
            groups.append(current)
            current = []
            tokens = 0
        current.append(section)
        tokens += section_tokens
    if current:
        groups.append(current)
    return groups


def _concatenate_sections(group: list[SectionNode]) -> tuple[str, list[tuple[int, int, int]], int, int]:
    """Join a group of sections into one text buffer with page-accurate spans."""

    pieces: list[str] = []
    spans: list[tuple[int, int, int]] = []
    offset = 0
    for index, section in enumerate(group):
        prefix = "" if index == 0 else "\n"
        start = offset + len(prefix)
        pieces.append(prefix + section.text)
        for span_start, span_end, page_number in section.page_spans:
            spans.append((start + span_start, start + span_end, page_number))
        offset = start + len(section.text)
    page_start = min(section.page_start for section in group)
    page_end = max(section.page_end for section in group)
    return "".join(pieces), spans, page_start, page_end


def _pages_for_range(
    page_spans: Sequence[tuple[int, int, int]],
    start: int,
    end: int,
    fallback: tuple[int, int],
) -> tuple[int, int]:
    pages = [
        page_number
        for span_start, span_end, page_number in page_spans
        if not (span_end <= start or span_start >= end)
    ]
    if not pages:
        return fallback
    return (min(pages), max(pages))


def merge_small_chunks(
    chunks: list[ChunkRecord],
    config: ChunkingConfig,
    counter: TokenCounter,
) -> list[ChunkRecord]:
    """Absorb undersized chunks into the previous chunk of the same document."""

    merged: list[ChunkRecord] = []
    for chunk in chunks:
        previous = merged[-1] if merged else None
        if (
            previous is not None
            and previous.document_id == chunk.document_id
            and chunk.token_count < config.min_tokens
            and previous.token_count + chunk.token_count <= config.max_tokens
        ):
            text = f"{previous.text}\n{chunk.text}"
            content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            heading_key = (
                " > ".join(previous.heading_path) if previous.heading_path else "prelude"
            )
            merged[-1] = ChunkRecord(
                chunk_id=make_chunk_id(
                    previous.document_id,
                    previous.page_start,
                    max(previous.page_end, chunk.page_end),
                    previous.stable_ordinal,
                    heading_key,
                    content_hash,
                ),
                document_id=previous.document_id,
                filename=previous.filename,
                document_type=previous.document_type,
                source_type=previous.source_type,
                manufacturer=previous.manufacturer,
                machine_family=previous.machine_family,
                model=previous.model,
                revision=previous.revision,
                publication_date=previous.publication_date,
                title=previous.title,
                language=previous.language,
                chapter=previous.chapter,
                section=previous.section,
                subsection=previous.subsection,
                heading_path=list(previous.heading_path),
                page_start=previous.page_start,
                page_end=max(previous.page_end, chunk.page_end),
                text=text,
                token_count=counter.count(text),
                content_hash=content_hash,
                embedding_model=previous.embedding_model,
                ingestion_version=previous.ingestion_version,
                document_sha256=previous.document_sha256,
                source_relative_path=previous.source_relative_path,
                section_ordinal=previous.section_ordinal,
                chunk_ordinal=previous.chunk_ordinal,
                stable_ordinal=previous.stable_ordinal,
                section_key=previous.section_key,
                heading_method=previous.heading_method,
            )
            continue
        merged.append(chunk)
    return merged


def build_document_chunks(
    document: DocumentNode,
    sections: list[SectionNode],
    config: ChunkingConfig,
    counter: TokenCounter,
    *,
    embedding_model: str,
    ingestion_version: str,
) -> list[ChunkRecord]:
    """Turn hierarchy sections into deterministic, embeddable chunks."""

    chunks: list[ChunkRecord] = []
    chunk_ordinal = 0
    for group in group_sections(sections, config, counter):
        group_text, page_spans, group_page_start, group_page_end = _concatenate_sections(group)
        representative = max(group, key=lambda section: len(section.text))
        heading_key = (
            " > ".join(representative.heading_path) if representative.heading_path else "prelude"
        )
        for range_ordinal, (start, end) in enumerate(split_section_text(group_text, config, counter), start=1):
            chunk_text = group_text[start:end].strip()
            if not chunk_text:
                continue
            chunk_ordinal += 1
            page_start, page_end = _pages_for_range(
                page_spans, start, end, (group_page_start, group_page_end)
            )
            content_hash = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
            stable_ordinal = representative.section_ordinal * 1000 + range_ordinal
            chunk_id = make_chunk_id(
                document.document_id,
                page_start,
                page_end,
                stable_ordinal,
                heading_key,
                content_hash,
            )
            chunks.append(
                ChunkRecord(
                    chunk_id=chunk_id,
                    document_id=document.document_id,
                    filename=document.filename,
                    document_type=document.document_type,
                    source_type=map_document_source_type(document.document_type).value,
                    manufacturer=document.manufacturer,
                    machine_family=document.machine_family,
                    model=document.model,
                    revision=document.revision,
                    publication_date=document.publication_date,
                    title=document.title,
                    language=document.language,
                    chapter=representative.chapter,
                    section=representative.section,
                    subsection=representative.subsection,
                    heading_path=list(representative.heading_path),
                    page_start=page_start,
                    page_end=page_end,
                    text=chunk_text,
                    token_count=counter.count(chunk_text),
                    content_hash=content_hash,
                    embedding_model=embedding_model,
                    ingestion_version=ingestion_version,
                    document_sha256=document.sha256,
                    source_relative_path=document.relative_path,
                    section_ordinal=representative.section_ordinal,
                    chunk_ordinal=chunk_ordinal,
                    stable_ordinal=stable_ordinal,
                    section_key=representative.section_key,
                    heading_method=representative.heading_method,
                )
            )
    return merge_small_chunks(chunks, config, counter)
