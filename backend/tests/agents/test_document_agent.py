from __future__ import annotations

import inspect
import typing
from pathlib import Path

import pytest

from app.agents.document import DocumentAgent, build_document_agent
from app.contracts import agents as agents_contract_module
from app.contracts import evidence as evidence_contract_module
from app.contracts.agents import AgentResult
from app.contracts.enums import AgentName, EvidenceSourceType, SourceKind
from app.contracts.evidence import Evidence, EvidenceProvenance
from app.contracts.query import QueryRequest
from app.core.exceptions import ProviderUnavailableError, RetrievalError
from app.protocols.agents import Agent


def make_query(**overrides) -> QueryRequest:
    fields: dict = {"query_id": "Q-1", "query": "spindle lubrication"}
    fields.update(overrides)
    return QueryRequest(**fields)


def make_evidence(index: int, score: float | None = None) -> Evidence:
    return Evidence(
        evidence_id=f"EVIDENCE-TEST-{index}",
        source_type=EvidenceSourceType.MANUAL,
        provenance=EvidenceProvenance(
            source_kind=SourceKind.DOCUMENT,
            source_dataset="manufacturaiq_document_corpus",
            source_id=f"CHUNK-{index}",
            document_id="DOC-42618F58C6C0",
            chunk_id=f"CHUNK-{index}",
            page_start=1,
            page_end=2,
        ),
        title=f"Title {index}",
        content=f"Content {index}",
        retrieval_score=0.9 - index * 0.05 if score is None else score,
        metadata={"retrieval_rank": index + 1},
    )


class FakeRetriever:
    """Stub DocumentRetriever living only inside backend/tests/agents."""

    def __init__(self, evidence: list[Evidence] | None = None, error: Exception | None = None):
        self._evidence = list(evidence or [])
        self._error = error
        self.calls: list[tuple[QueryRequest, int]] = []

    async def retrieve(self, query: QueryRequest, top_k: int = 10) -> list[Evidence]:
        self.calls.append((query, top_k))
        if self._error is not None:
            raise self._error
        return list(self._evidence)[:top_k]


def test_agent_satisfies_frozen_agent_protocol() -> None:
    assert inspect.iscoroutinefunction(DocumentAgent.run)
    hints = typing.get_type_hints(DocumentAgent.run)
    assert hints["query"] is QueryRequest
    assert hints["return"] is AgentResult
    assert hasattr(DocumentAgent(FakeRetriever()), "run")


def test_agent_protocol_shape_matches() -> None:
    agent_hints = typing.get_type_hints(Agent.run)
    impl_hints = typing.get_type_hints(DocumentAgent.run)
    assert agent_hints["query"] is impl_hints["query"]
    assert agent_hints["return"] is impl_hints["return"]


async def test_returns_document_agent_name() -> None:
    result = await DocumentAgent(FakeRetriever([make_evidence(0)])).run(make_query())

    assert result.agent_name is AgentName.DOCUMENT
    assert result.agent_name.value == "DOCUMENT"


async def test_preserves_query_id() -> None:
    result = await DocumentAgent(FakeRetriever()).run(make_query(query_id="Q-UNIQUE-123"))

    assert result.query_id == "Q-UNIQUE-123"


async def test_passes_original_query_request_to_retriever() -> None:
    retriever = FakeRetriever([make_evidence(0)])
    query = make_query(user_context={"document_type": "MANUAL"})

    await DocumentAgent(retriever, top_k=5).run(query)

    assert len(retriever.calls) == 1
    received, received_top_k = retriever.calls[0]
    assert received is query
    assert received_top_k == 5


async def test_uses_configured_top_k_by_default() -> None:
    retriever = FakeRetriever([make_evidence(index) for index in range(12)])

    result = await DocumentAgent(retriever).run(make_query())

    assert retriever.calls[0][1] == 8
    assert len(result.evidence) == 8


async def test_uses_explicit_top_k() -> None:
    retriever = FakeRetriever([make_evidence(index) for index in range(5)])

    result = await DocumentAgent(retriever, top_k=3).run(make_query())

    assert retriever.calls[0][1] == 3
    assert len(result.evidence) == 3


@pytest.mark.parametrize("bad_top_k", [0, -2, "8", 4.5, True])
def test_invalid_top_k_is_rejected_loudly(bad_top_k) -> None:
    with pytest.raises(ValueError):
        DocumentAgent(FakeRetriever(), top_k=bad_top_k)


async def test_preserves_evidence_objects_and_order() -> None:
    evidence = [make_evidence(index) for index in range(4)]

    result = await DocumentAgent(FakeRetriever(evidence), top_k=8).run(make_query())

    assert [item.evidence_id for item in result.evidence] == [item.evidence_id for item in evidence]
    assert all(first is second for first, second in zip(result.evidence, evidence))


async def test_preserves_retrieval_scores() -> None:
    evidence = [make_evidence(index) for index in range(3)]

    result = await DocumentAgent(FakeRetriever(evidence), top_k=8).run(make_query())

    assert [item.retrieval_score for item in result.evidence] == [
        item.retrieval_score for item in evidence
    ]


async def test_never_sets_decision_score() -> None:
    evidence = [make_evidence(index) for index in range(3)]

    result = await DocumentAgent(FakeRetriever(evidence), top_k=8).run(make_query())

    assert all(item.decision_score is None for item in result.evidence)


async def test_empty_retrieval_returns_warning_not_error() -> None:
    result = await DocumentAgent(FakeRetriever([])).run(make_query(query_id="Q-EMPTY"))

    assert result.evidence == []
    assert result.errors == []
    assert result.warnings == ["No document evidence retrieved."]
    assert result.query_id == "Q-EMPTY"
    assert result.metadata["retrieval_status"] == "empty"
    assert result.metadata["retrieved_count"] == 0


@pytest.mark.parametrize(
    "failure",
    [
        RetrievalError("index offline"),
        ProviderUnavailableError("provider down"),
        ConnectionError("connection refused"),
    ],
)
async def test_expected_retrieval_failure_returns_safe_errors(failure: Exception) -> None:
    result = await DocumentAgent(FakeRetriever(error=failure)).run(make_query())

    assert result.evidence == []
    assert len(result.errors) == 1
    assert result.errors[0].startswith("Document retrieval failed: ")
    assert "Traceback" not in result.errors[0]
    assert result.metadata["retrieval_status"] == "failed"
    assert result.metadata["retrieved_count"] == 0
    assert result.latency_ms is not None and result.latency_ms >= 0


async def test_unexpected_programming_error_is_not_swallowed() -> None:
    agent = DocumentAgent(FakeRetriever(error=RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        await agent.run(make_query())


async def test_latency_is_populated_and_non_negative() -> None:
    result = await DocumentAgent(FakeRetriever([make_evidence(0)])).run(make_query())

    assert isinstance(result.latency_ms, float)
    assert result.latency_ms >= 0


async def test_metadata_reports_evidence_count() -> None:
    result = await DocumentAgent(FakeRetriever([make_evidence(0), make_evidence(1)]), top_k=8).run(
        make_query()
    )

    assert result.metadata["retrieved_count"] == 2
    assert result.metadata["requested_top_k"] == 8
    assert result.metadata["retriever"] == "FakeRetriever"
    assert result.metadata["retrieval_status"] == "ok"


async def test_no_evidence_duplication() -> None:
    evidence = [make_evidence(index) for index in range(5)]

    result = await DocumentAgent(FakeRetriever(evidence), top_k=8).run(make_query())

    ids = [item.evidence_id for item in result.evidence]
    assert len(ids) == len(set(ids)) == len(evidence)


async def test_user_context_passes_through_unchanged() -> None:
    retriever = FakeRetriever([make_evidence(0)])
    query = make_query(user_context={"document_type": "MANUAL", "language": "en"})

    await DocumentAgent(retriever).run(query)

    received = retriever.calls[0][0]
    assert received.user_context == {"document_type": "MANUAL", "language": "en"}


async def test_machine_id_is_not_converted_into_document_filters() -> None:
    retriever = FakeRetriever([make_evidence(0)])
    query = make_query(machine_id="CNC-05")

    await DocumentAgent(retriever).run(query)

    received = retriever.calls[0][0]
    assert received.machine_id == "CNC-05"
    assert received.user_context == {}


async def test_product_id_is_not_converted_into_document_filters() -> None:
    retriever = FakeRetriever([make_evidence(0)])
    query = make_query(product_id="SHAFT-A")

    await DocumentAgent(retriever).run(query)

    received = retriever.calls[0][0]
    assert received.product_id == "SHAFT-A"
    assert received.user_context == {}


async def test_batch_id_is_not_converted_into_document_filters() -> None:
    retriever = FakeRetriever([make_evidence(0)])
    query = make_query(batch_id="B-77")

    await DocumentAgent(retriever).run(query)

    received = retriever.calls[0][0]
    assert received.batch_id == "B-77"
    assert received.user_context == {}


async def test_fewer_results_than_requested_warns() -> None:
    result = await DocumentAgent(FakeRetriever([make_evidence(0), make_evidence(1)]), top_k=8).run(
        make_query()
    )

    assert result.errors == []
    assert result.warnings == ["Retriever returned 2 of 8 requested evidence items."]


def test_module_respects_dependency_boundaries() -> None:
    source = (Path(__file__).resolve().parents[2] / "app" / "agents" / "document.py").read_text(
        encoding="utf-8"
    )
    lowered = source.lower()
    for forbidden in (
        "app.repositories",
        "app.db",
        "app.reasoning",
        "app.decision",
        "app.orchestration",
        "gemini",
        "langgraph",
        "typesafe",
        "groq",
        "openai",
    ):
        assert forbidden not in lowered, f"forbidden dependency reference: {forbidden}"
    assert "VectorStore(" not in source
    assert "build_embedding_model(" not in source


def test_returns_frozen_contract_models() -> None:
    assert agents_contract_module.AgentResult is AgentResult
    assert evidence_contract_module.Evidence is Evidence
    assert AgentResult.__module__ == "app.contracts.agents"
    assert Evidence.__module__ == "app.contracts.evidence"


def _real_index_available() -> bool:
    from app.core.config import get_settings
    from app.rag.ingestion import load_manifest

    settings = get_settings()
    manifest = load_manifest(settings.vector_store_path / "manifest.json")
    return manifest is not None and settings.document_chunks_path.exists()


@pytest.mark.parametrize(
    "query_text",
    [
        "lockout tagout hazardous energy",
        "SINUMERIK tool management",
        "lathe chuck safety",
        "Siemens alarm reset",
    ],
)
async def test_read_only_integration_with_real_retriever(query_text: str) -> None:
    if not _real_index_available():
        pytest.skip("canonical RAG index not built; run app.rag.ingestion first")
    from app.core.config import get_settings
    from app.rag.retrieval import DocumentRetrieverImpl

    settings = get_settings()
    retriever = DocumentRetrieverImpl(settings=settings)
    try:
        agent = DocumentAgent(retriever)
        result = await agent.run(make_query(query_id=f"Q-INT-{query_text[:8]}", query=query_text))
    finally:
        retriever.close()

    assert result.agent_name is AgentName.DOCUMENT
    assert result.evidence, f"expected document evidence for {query_text!r}"
    for item in result.evidence:
        assert isinstance(item, Evidence)
        assert item.provenance.document_id
        assert item.provenance.page_start is not None
        assert item.retrieval_score is not None
        assert item.decision_score is None
