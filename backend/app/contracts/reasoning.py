from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from .base import ContractModel
from .enums import ProviderStatus


class EvidenceCitation(ContractModel):
    """Citation by evidence ID; source resolution happens later."""

    evidence_id: str = Field(min_length=1)
    label: str | None = None


class ReasoningResult(ContractModel):
    """Evidence-grounded reasoning output from a future LLM reasoner."""

    query_id: str = Field(min_length=1)
    observations: list[str] = Field(default_factory=list)
    possible_causes: list[str] = Field(default_factory=list)
    recommended_checks: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    citations: list[EvidenceCitation] = Field(default_factory=list)
    raw_answer: str
    provider_status: ProviderStatus
    model: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("raw_answer")
    @classmethod
    def raw_answer_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("raw_answer must not be empty")
        return value

