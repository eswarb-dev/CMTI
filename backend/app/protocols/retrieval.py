from __future__ import annotations

from typing import Protocol

from app.contracts.evidence import Evidence
from app.contracts.query import QueryRequest


class DocumentRetriever(Protocol):
    """Future hierarchical document retrieval interface."""

    async def retrieve(self, query: QueryRequest, top_k: int = 10) -> list[Evidence]:
        """Retrieve document evidence for a query."""

