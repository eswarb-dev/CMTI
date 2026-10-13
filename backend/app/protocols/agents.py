from __future__ import annotations

from typing import Protocol

from app.contracts.agents import AgentResult
from app.contracts.query import QueryRequest


class Agent(Protocol):
    """Async protocol implemented by future domain agents."""

    async def run(self, query: QueryRequest) -> AgentResult:
        """Return evidence for a query without producing the final answer."""

