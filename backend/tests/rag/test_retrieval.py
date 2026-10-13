from __future__ import annotations

import pytest

from app.contracts.evidence import Evidence
from app.contracts.enums import EvidenceSourceType
from app.contracts.query import QueryRequest


def make_query(text: str, **kwargs) -> QueryRequest:
    defaults = dict(query_id="Q-RAG", query=text, user_context={})
    defaults.update(kwargs)
    return QueryRequest(**defaults)


async def test_retrieve_returns_evidence_list_within_requested_top_k(retriever, settings) -> None:
    evidences = await retriever.retrieve(make_query("G00 rapid motion"), top_k=5)

    assert 1 <= len(evidences) <= 5
    assert all(isinstance(item, Evidence) for item in evidences)
    assert len({item.provenance.chunk_id for item in evidences}) == len(evidences)

    default_budget = await retriever.retrieve(make_query("G00 rapid motion"))
    assert 1 <= len(default_budget) <= 10


async def test_top_k_is_validated_and_clamped(retriever, settings) -> None:
    with pytest.raises(ValueError):
        await retriever.retrieve(make_query("G00 rapid motion"), top_k=0)

    oversized = await retriever.retrieve(make_query("G00 rapid motion"), top_k=100_000)
    assert len(oversized) <= settings.rag_max_top_k


async def test_machine_and_product_identity_never_restrict_the_corpus(retriever) -> None:
    plain = await retriever.retrieve(make_query("how do I set a tool offset"), top_k=5)
    bound = await retriever.retrieve(
        make_query(
            "how do I set a tool offset",
            machine_id="CNC-99",
            product_id="SHAFT-A",
            batch_id="B-77",
        ),
        top_k=5,
    )

    assert plain and bound
    assert [item.provenance.chunk_id for item in bound] == [
        item.provenance.chunk_id for item in plain
    ]


async def test_document_type_filter_restricts_every_returned_evidence(retriever) -> None:
    safety = await retriever.retrieve(
        make_query("lockout tagout energy control", user_context={"document_type": "SAFETY"}),
        top_k=5,
    )
    assert safety
    assert all(item.source_type is EvidenceSourceType.SAFETY for item in safety)
    assert all(item.provenance.document_id == "DOC-3EA7380FA108" for item in safety)

    manual = await retriever.retrieve(
        make_query("G00 rapid motion", user_context={"document_type": "MANUAL"}),
        top_k=5,
    )
    assert manual
    assert all(item.source_type is EvidenceSourceType.MANUAL for item in manual)
    assert all(item.provenance.document_id != "DOC-3EA7380FA108" for item in manual)


async def test_repeated_queries_return_identical_rankings(retriever) -> None:
    first = await retriever.retrieve(make_query("spindle lubrication"), top_k=5)
    second = await retriever.retrieve(make_query("spindle lubrication"), top_k=5)

    assert [item.provenance.chunk_id for item in first] == [
        item.provenance.chunk_id for item in second
    ]
    assert [item.retrieval_score for item in first] == [item.retrieval_score for item in second]


async def test_lockout_tagout_query_surfaces_the_safety_manual_first(retriever) -> None:
    evidences = await retriever.retrieve(
        make_query("What is the lockout/tagout procedure?"), top_k=5
    )

    assert evidences
    assert evidences[0].source_type is EvidenceSourceType.SAFETY
    assert evidences[0].provenance.document_id == "DOC-3EA7380FA108"


def test_retrieval_quality_meets_the_fixture_thresholds(retrieval_quality) -> None:
    metrics = retrieval_quality["metrics"]
    thresholds = retrieval_quality["thresholds"]
    results = retrieval_quality["case_results"]

    assert metrics["cases"] == len(results) >= 10
    for name in ("hit_at_1", "hit_at_3", "hit_at_5", "mrr"):
        assert metrics[name] >= thresholds[name], f"{name}={metrics[name]} < {thresholds[name]}"

    checks = {check.name: check.status for check in retrieval_quality["checks"]}
    assert checks["retrieval_fixture_present"] == "PASS"
    assert checks["retrieval_cases_evaluated"] == "PASS"
    assert checks["evidence_source_type_scope"] == "PASS"
