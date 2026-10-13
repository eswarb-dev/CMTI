from __future__ import annotations

from typing import Protocol

from app.contracts.evidence import Evidence
from app.contracts.fusion import EvidenceBundle
from app.contracts.query import QueryRequest
from app.contracts.reasoning import ReasoningResult
from app.contracts.review import ReviewDecision
from app.contracts.routing import RoutingDecision


class DecisionEngine(Protocol):
    """Provider-neutral bounded decision interface for future Jev integration."""

    async def route(self, query: QueryRequest) -> RoutingDecision:
        """Route a query to selected agents."""

    async def score_evidence(self, query: QueryRequest, evidence: list[Evidence]) -> list[Evidence]:
        """Score candidate evidence without mutating hidden ground truth."""

    async def review(
        self,
        query: QueryRequest,
        bundle: EvidenceBundle,
        reasoning: ReasoningResult,
    ) -> ReviewDecision:
        """Review the final reasoning result."""

