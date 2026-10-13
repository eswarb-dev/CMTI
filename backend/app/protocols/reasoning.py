from __future__ import annotations

from typing import Protocol

from app.contracts.fusion import EvidenceBundle
from app.contracts.query import QueryRequest
from app.contracts.reasoning import ReasoningResult


class Reasoner(Protocol):
    """Future evidence-grounded reasoner interface."""

    async def reason(self, query: QueryRequest, evidence: EvidenceBundle) -> ReasoningResult:
        """Produce observations, hypotheses, checks, and citations."""

