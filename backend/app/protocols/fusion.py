from __future__ import annotations

from typing import Protocol

from app.contracts.agents import AgentResult
from app.contracts.fusion import EvidenceBundle
from app.contracts.query import QueryRequest


class EvidenceFusionService(Protocol):
    """Future evidence fusion and validation interface."""

    async def fuse(self, query: QueryRequest, agent_results: list[AgentResult]) -> EvidenceBundle:
        """Fuse agent results into a bundle."""

