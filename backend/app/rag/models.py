from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from ..contracts.enums import EvidenceSourceType

INGESTION_VERSION = "step06.v1"
SOURCE_DATASET = "manufacturaiq_document_corpus"

# Fields written to document_chunks.parquet and to the Qdrant payload.
CHUNK_FIELDS: tuple[str, ...] = (
    "chunk_id",
    "document_id",
    "filename",
    "document_type",
    "source_type",
    "manufacturer",
    "machine_family",
    "model",
    "revision",
    "publication_date",
    "title",
    "language",
    "chapter",
    "section",
    "subsection",
    "heading_path",
    "page_start",
    "page_end",
    "text",
    "token_count",
    "content_hash",
    "embedding_model",
    "ingestion_version",
    "document_sha256",
    "source_relative_path",
    "section_ordinal",
    "chunk_ordinal",
    "stable_ordinal",
    "section_key",
    "heading_method",
)


@dataclass(slots=True)
class DocumentNode:
    """Document-level metadata reconstructed from staged artifacts."""

    document_id: str
    filename: str
    relative_path: str
    document_type: str
    manufacturer: str | None = None
    machine_family: str | None = None
    model: str | None = None
    title: str | None = None
    revision: str | None = None
    publication_date: str | None = None
    language: str | None = None
    page_count: int | None = None
    sha256: str | None = None

    @classmethod
    def from_manifest_entry(cls, entry: dict[str, Any]) -> "DocumentNode":
        return cls(
            document_id=entry["document_id"],
            filename=entry.get("filename") or entry["document_id"],
            relative_path=entry.get("relative_path") or "",
            document_type=entry.get("document_type") or "UNKNOWN",
            manufacturer=entry.get("manufacturer"),
            machine_family=entry.get("machine_family"),
            model=entry.get("model"),
            title=entry.get("title"),
            revision=entry.get("revision"),
            publication_date=entry.get("publication_date"),
            language=entry.get("language"),
            page_count=entry.get("page_count"),
            sha256=entry.get("sha256"),
        )


@dataclass(slots=True)
class PageRecord:
    """One extracted page from the staged document page table."""

    document_id: str
    page_number: int
    text: str
    page_quality: str = "UNKNOWN"
    is_sample_page: bool = False


@dataclass(slots=True)
class HeadingMatch:
    """A heading detected on a single page line."""

    level: int
    text: str
    method: str
    page_number: int
    line_index: int
    consumed_lines: int = 0


@dataclass(slots=True)
class SectionNode:
    """A contiguous, heading-scoped region of one document."""

    document_id: str
    section_ordinal: int
    heading_path: list[str] = field(default_factory=list)
    chapter: str | None = None
    section: str | None = None
    subsection: str | None = None
    level: int = 0
    page_start: int = 0
    page_end: int = 0
    text: str = ""
    page_spans: list[tuple[int, int, int]] = field(default_factory=list)
    heading_method: str = "document_start"

    @property
    def section_key(self) -> str:
        if not self.heading_path:
            return f"{self.document_id}::prelude"
        return f"{self.document_id}::{' > '.join(self.heading_path)}"

    def pages_for_range(self, start: int, end: int) -> tuple[int, int]:
        pages: list[int] = []
        for span_start, span_end, page_number in self.page_spans:
            if span_end <= start or span_start >= end:
                continue
            pages.append(page_number)
        if not pages:
            return (self.page_start, self.page_end)
        return (min(pages), max(pages))


@dataclass(slots=True)
class ChunkRecord:
    """One embeddable chunk with section-aware provenance metadata."""

    chunk_id: str
    document_id: str
    filename: str
    document_type: str
    source_type: str
    manufacturer: str | None
    machine_family: str | None
    model: str | None
    revision: str | None
    publication_date: str | None
    title: str | None
    language: str | None
    chapter: str | None
    section: str | None
    subsection: str | None
    heading_path: list[str]
    page_start: int
    page_end: int
    text: str
    token_count: int
    content_hash: str
    embedding_model: str
    ingestion_version: str
    document_sha256: str | None
    source_relative_path: str
    section_ordinal: int
    chunk_ordinal: int
    stable_ordinal: int
    section_key: str
    heading_method: str

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ChunkRecord":
        return cls(**{name: payload.get(name) for name in CHUNK_FIELDS})


def map_document_source_type(document_type: str | None) -> EvidenceSourceType:
    """Map a staged document type onto the frozen STEP 04 evidence enum."""

    normalized = re.sub(r"[\s\-]+", "_", (document_type or "").strip().upper())
    if normalized.endswith("_SAFETY") or normalized in {"SAFETY", "SAFETY_NOTICE"}:
        return EvidenceSourceType.SAFETY
    if normalized.startswith("SOP"):
        return EvidenceSourceType.SOP
    if normalized.endswith("_MANUAL") or normalized in {
        "MANUAL",
        "TECHNICAL_REFERENCE",
        "TECHNICAL_MANUAL",
        "GUIDE",
        "SPECIFICATION",
    }:
        return EvidenceSourceType.MANUAL
    # Deterministic fallback: everything in the document corpus is a manual
    # unless it is explicitly safety- or procedure-like. EXTERNAL_DATASET is
    # reserved for tabular external datasets, never for document chunks.
    return EvidenceSourceType.MANUAL
