from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from .base import ContractModel
from .enums import RiskLevel
from .evidence import Evidence


class EvidenceConflict(ContractModel):
    """Conflict detected during evidence fusion."""

    conflict_id: str = Field(min_length=1)
    evidence_ids: list[str]
    conflict_type: str
    description: str
    severity: RiskLevel
    resolved: bool
    resolution_note: str | None = None

    @field_validator("evidence_ids")
    @classmethod
    def evidence_ids_required(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("evidence_ids must not be empty")
        if any(not item.strip() for item in value):
            raise ValueError("evidence_ids must not contain empty identifiers")
        return value


class EvidenceBundle(ContractModel):
    """Fused and validated evidence bundle for the future reasoner."""

    query_id: str = Field(min_length=1)
    evidence: list[Evidence] = Field(default_factory=list)
    conflicts: list[EvidenceConflict] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

