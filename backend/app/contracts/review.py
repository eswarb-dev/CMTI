from __future__ import annotations

from typing import Any

from pydantic import Field

from .base import ContractModel
from .enums import ProviderStatus, ReviewAction


class ReviewDecision(ContractModel):
    """Review gate decision after evidence-grounded reasoning."""

    query_id: str = Field(min_length=1)
    action: ReviewAction
    reasons: list[str] = Field(default_factory=list)
    confidence: float | None = None
    provider_status: ProviderStatus
    metadata: dict[str, Any] = Field(default_factory=dict)

