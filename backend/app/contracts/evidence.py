from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, field_validator, model_validator

from .base import ContractModel
from .enums import EvidenceSourceType, SourceKind


class EvidenceProvenance(ContractModel):
    """Source provenance for evidence from documents or structured data."""

    source_kind: SourceKind
    source_dataset: str
    source_id: str
    source_file: str | None = None
    document_id: str | None = None
    record_id: str | None = None
    raw_record_id: str | None = None
    chunk_id: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    chapter: str | None = None
    section: str | None = None
    subsection: str | None = None

    @field_validator("source_dataset", "source_id")
    @classmethod
    def non_empty_source_fields(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source provenance identifiers must not be empty")
        return value

    @field_validator("page_start", "page_end")
    @classmethod
    def page_numbers_positive(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("page numbers must be positive")
        return value

    @model_validator(mode="after")
    def page_range_valid(self) -> "EvidenceProvenance":
        if self.page_start is not None and self.page_end is not None and self.page_start > self.page_end:
            raise ValueError("page_start must be before or equal to page_end")
        return self


class Evidence(ContractModel):
    """Common evidence currency returned by all future agents."""

    evidence_id: str = Field(min_length=1)
    source_type: EvidenceSourceType
    provenance: EvidenceProvenance
    machine_id: str | None = None
    product_id: str | None = None
    batch_id: str | None = None
    title: str
    content: str
    observed_at: datetime | None = None
    retrieval_score: float | None = None
    decision_score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("evidence_id", "title", "content")
    @classmethod
    def required_text_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("required evidence text fields must not be empty")
        return value

