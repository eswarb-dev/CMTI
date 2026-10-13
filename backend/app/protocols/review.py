from __future__ import annotations

from typing import Protocol

from app.contracts.fusion import EvidenceBundle
from app.contracts.query import QueryRequest
from app.contracts.reasoning import ReasoningResult
from app.contracts.review import ReviewDecision


class ReviewGate(Protocol):
    """Future final review gate interface."""

    async def evaluate(
        self,
        query: QueryRequest,
        evidence: EvidenceBundle,
        reasoning: ReasoningResult,
    ) -> ReviewDecision:
        """Evaluate whether reasoning can pass or needs human review."""

