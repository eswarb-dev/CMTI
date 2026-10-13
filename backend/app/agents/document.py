from __future__ import annotations

import time
from typing import Any

from app.contracts.agents import AgentResult
from app.contracts.enums import AgentName
from app.contracts.query import QueryRequest
from app.core.config import Settings, get_settings
from app.core.exceptions import ProviderUnavailableError, RetrievalError
from app.protocols.retrieval import DocumentRetriever

__all__ = ["DocumentAgent", "build_document_agent"]

#: Retrieval-layer failures that map to a safe, successful-shape AgentResult
#: instead of propagating. Anything else stays visible.
EXPECTED_RETRIEVAL_FAILURES = (
    RetrievalError,
    ProviderUnavailableError,
    ConnectionError,
    TimeoutError,
)


class DocumentAgent:
    """Answers "what document evidence is relevant?" and nothing more.

    Thin async wrapper over the ``DocumentRetriever`` protocol: it forwards
    the original ``QueryRequest`` unchanged, preserves the returned frozen
    ``Evidence`` objects and their order, and packages them into a frozen
    ``AgentResult``. No reasoning, no diagnosis, no summarisation, no LLM,
    no database access, no fusion.
    """

    def __init__(
        self,
        retriever: DocumentRetriever,
        *,
        top_k: int | None = None,
        settings: Settings | None = None,
    ) -> None:
        if top_k is not None:
            if isinstance(top_k, bool) or not isinstance(top_k, int):
                raise ValueError("top_k must be an integer")
            if top_k < 1:
                raise ValueError("top_k must be greater than zero")
        self._retriever = retriever
        self._settings = settings or get_settings()
        self._top_k = top_k if top_k is not None else self._settings.document_agent_top_k

    @property
    def retriever(self) -> DocumentRetriever:
        return self._retriever

    @property
    def top_k(self) -> int:
        return self._top_k

    def _metadata(self, status: str, retrieved_count: int) -> dict[str, Any]:
        return {
            "retrieved_count": retrieved_count,
            "requested_top_k": self._top_k,
            "retriever": type(self._retriever).__name__,
            "retrieval_status": status,
        }

    @staticmethod
    def _latency_ms(started: float) -> float:
        return max(0.0, (time.perf_counter() - started) * 1000.0)

    async def run(self, query: QueryRequest) -> AgentResult:
        """Retrieve document evidence for ``query`` without interpreting it."""

        started = time.perf_counter()
        try:
            evidence = await self._retriever.retrieve(query, top_k=self._top_k)
        except EXPECTED_RETRIEVAL_FAILURES as exc:
            return AgentResult(
                agent_name=AgentName.DOCUMENT,
                query_id=query.query_id,
                evidence=[],
                errors=[f"Document retrieval failed: {exc}"],
                latency_ms=self._latency_ms(started),
                metadata=self._metadata("failed", 0),
            )
        # Unexpected programming defects propagate; they must stay visible.

        warnings: list[str] = []
        if not evidence:
            warnings.append("No document evidence retrieved.")
            status = "empty"
        else:
            status = "ok"
            if len(evidence) < self._top_k:
                warnings.append(
                    f"Retriever returned {len(evidence)} of {self._top_k} requested evidence items."
                )
        return AgentResult(
            agent_name=AgentName.DOCUMENT,
            query_id=query.query_id,
            evidence=list(evidence),
            warnings=warnings,
            latency_ms=self._latency_ms(started),
            metadata=self._metadata(status, len(evidence)),
        )


def build_document_agent(
    settings: Settings | None = None,
    retriever: DocumentRetriever | None = None,
    embedder: Any | None = None,
) -> DocumentAgent:
    """Construct a DocumentAgent on the canonical local RAG retriever."""

    from app.rag.retrieval import DocumentRetrieverImpl

    resolved = settings or get_settings()
    return DocumentAgent(
        retriever or DocumentRetrieverImpl(settings=resolved, embedder=embedder),
        settings=resolved,
    )
