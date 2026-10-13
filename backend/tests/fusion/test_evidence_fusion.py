from __future__ import annotations

import copy
import inspect
import typing
from datetime import datetime
from pathlib import Path

import pytest

from app.contracts.agents import AgentResult
from app.contracts.enums import AgentName, EvidenceSourceType, RiskLevel, SourceKind
from app.contracts.evidence import Evidence, EvidenceProvenance
from app.contracts.fusion import EvidenceBundle, EvidenceConflict
from app.contracts.query import QueryRequest
from app.fusion.service import DeterministicEvidenceFusionService, build_evidence_fusion_service
from app.protocols.fusion import EvidenceFusionService


def make_query(**overrides) -> QueryRequest:
    fields: dict = {"query_id": "Q-FUSE-1", "query": "fuse evidence"}
    fields.update(overrides)
    return QueryRequest(**fields)


def make_evidence(
    evidence_id: str = "EV-001",
    source_type: EvidenceSourceType = EvidenceSourceType.MANUAL,
    source_kind: SourceKind = SourceKind.DOCUMENT,
    source_dataset: str = "manufacturaiq_demo_factory",
    source_id: str = "DOC-001",
    record_id: str | None = None,
    document_id: str | None = "DOC-001",
    chunk_id: str | None = None,
    page_start: int | None = None,
    page_end: int | None = None,
    title: str = "Test Evidence",
    content: str = "Test content",
    machine_id: str | None = None,
    product_id: str | None = None,
    batch_id: str | None = None,
    observed_at: datetime | None = None,
    retrieval_score: float | None = None,
    decision_score: float | None = None,
    metadata: dict | None = None,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        source_type=source_type,
        provenance=EvidenceProvenance(
            source_kind=source_kind,
            source_dataset=source_dataset,
            source_id=source_id,
            record_id=record_id,
            document_id=document_id,
            chunk_id=chunk_id,
            page_start=page_start,
            page_end=page_end,
        ),
        machine_id=machine_id,
        product_id=product_id,
        batch_id=batch_id,
        title=title,
        content=content,
        observed_at=observed_at,
        retrieval_score=retrieval_score,
        decision_score=decision_score,
        metadata=metadata or {},
    )


def make_agent_result(
    agent_name: AgentName = AgentName.DOCUMENT,
    query_id: str = "Q-FUSE-1",
    evidence: list[Evidence] | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
) -> AgentResult:
    return AgentResult(
        agent_name=agent_name,
        query_id=query_id,
        evidence=evidence or [],
        warnings=warnings or [],
        errors=errors or [],
    )


def make_service() -> DeterministicEvidenceFusionService:
    return DeterministicEvidenceFusionService()


def test_satisfies_frozen_evidence_fusion_service_protocol() -> None:
    assert inspect.iscoroutinefunction(DeterministicEvidenceFusionService.fuse)
    hints = typing.get_type_hints(DeterministicEvidenceFusionService.fuse)
    assert hints["query"] is QueryRequest
    assert hints["agent_results"] == list[AgentResult]
    assert hints["return"] is EvidenceBundle
    agent_hints = typing.get_type_hints(EvidenceFusionService.fuse)
    assert agent_hints["query"] is hints["query"]
    assert agent_hints["agent_results"] == hints["agent_results"]
    assert agent_hints["return"] is hints["return"]


async def test_returns_frozen_evidence_bundle() -> None:
    service = make_service()
    result = await service.fuse(make_query(), [])
    assert isinstance(result, EvidenceBundle)


async def test_common_query_id_preserved() -> None:
    service = make_service()
    result = await service.fuse(make_query(query_id="Q-ABC"), [])
    assert result.query_id == "Q-ABC"


async def test_mismatched_query_ids_rejected() -> None:
    service = make_service()
    results = [make_agent_result(query_id="Q-DIFFERENT")]
    with pytest.raises(ValueError, match="query_id mismatch"):
        await service.fuse(make_query(query_id="Q-ORIGINAL"), results)


async def test_no_generated_replacement_query_id() -> None:
    service = make_service()
    result = await service.fuse(make_query(query_id="Q-REAL"), [])
    assert result.query_id != "unknown"
    assert result.query_id == "Q-REAL"


async def test_empty_input_returns_empty_bundle() -> None:
    service = make_service()
    result = await service.fuse(make_query(), [])
    assert result.evidence == []
    assert result.conflicts == []
    assert result.metadata["evidence_input_count"] == 0
    assert result.metadata["evidence_output_count"] == 0


async def test_evidence_from_all_four_agents_fused() -> None:
    service = make_service()
    results = [
        make_agent_result(AgentName.DOCUMENT, evidence=[make_evidence("EV-D1", source_id="DOC-001")]),
        make_agent_result(AgentName.MAINTENANCE, evidence=[make_evidence("EV-M1", source_type=EvidenceSourceType.MAINTENANCE, source_kind=SourceKind.DEMO_FACTORY, source_id="MNT-001")]),
        make_agent_result(AgentName.QUALITY, evidence=[make_evidence("EV-Q1", source_type=EvidenceSourceType.QUALITY, source_kind=SourceKind.DEMO_FACTORY, source_id="QI-001")]),
        make_agent_result(AgentName.PRODUCTION, evidence=[make_evidence("EV-P1", source_type=EvidenceSourceType.PRODUCTION, source_kind=SourceKind.DEMO_FACTORY, source_id="PO-001")]),
    ]
    result = await service.fuse(make_query(), results)
    assert len(result.evidence) == 4


async def test_canonical_agent_ordering_independent_of_input_order() -> None:
    service = make_service()
    results_forward = [
        make_agent_result(AgentName.DOCUMENT, evidence=[make_evidence("EV-D1")]),
        make_agent_result(AgentName.MAINTENANCE, evidence=[make_evidence("EV-M1", source_type=EvidenceSourceType.MAINTENANCE, source_kind=SourceKind.DEMO_FACTORY)]),
        make_agent_result(AgentName.QUALITY, evidence=[make_evidence("EV-Q1", source_type=EvidenceSourceType.QUALITY, source_kind=SourceKind.DEMO_FACTORY)]),
        make_agent_result(AgentName.PRODUCTION, evidence=[make_evidence("EV-P1", source_type=EvidenceSourceType.PRODUCTION, source_kind=SourceKind.DEMO_FACTORY)]),
    ]
    results_reversed = list(reversed(results_forward))
    r1 = await service.fuse(make_query(), results_forward)
    r2 = await service.fuse(make_query(), results_reversed)
    assert [e.evidence_id for e in r1.evidence] == [e.evidence_id for e in r2.evidence]


async def test_document_local_order_preserved() -> None:
    service = make_service()
    ev1 = make_evidence("EV-D1", source_id="DOC-001")
    ev2 = make_evidence("EV-D2", source_id="DOC-002")
    ev3 = make_evidence("EV-D3", source_id="DOC-003")
    results = [make_agent_result(AgentName.DOCUMENT, evidence=[ev1, ev2, ev3])]
    result = await service.fuse(make_query(), results)
    doc_ids = [e.evidence_id for e in result.evidence if e.source_type == EvidenceSourceType.MANUAL]
    assert doc_ids == ["EV-D1", "EV-D2", "EV-D3"]


async def test_maintenance_local_order_preserved() -> None:
    service = make_service()
    ev1 = make_evidence("EV-M1", source_type=EvidenceSourceType.MAINTENANCE, source_kind=SourceKind.DEMO_FACTORY, source_id="MNT-001")
    ev2 = make_evidence("EV-M2", source_type=EvidenceSourceType.ALARM, source_kind=SourceKind.DEMO_FACTORY, source_id="ALM-001")
    ev3 = make_evidence("EV-M3", source_type=EvidenceSourceType.TELEMETRY, source_kind=SourceKind.DEMO_FACTORY, source_id="TEL-001")
    results = [make_agent_result(AgentName.MAINTENANCE, evidence=[ev1, ev2, ev3])]
    result = await service.fuse(make_query(), results)
    mnt_ids = [e.evidence_id for e in result.evidence]
    assert mnt_ids == ["EV-M1", "EV-M2", "EV-M3"]


async def test_quality_local_order_preserved() -> None:
    service = make_service()
    ev1 = make_evidence("EV-Q1", source_type=EvidenceSourceType.QUALITY, source_kind=SourceKind.DEMO_FACTORY, source_id="QI-001")
    ev2 = make_evidence("EV-Q2", source_type=EvidenceSourceType.QUALITY, source_kind=SourceKind.DEMO_FACTORY, source_id="QI-002")
    results = [make_agent_result(AgentName.QUALITY, evidence=[ev1, ev2])]
    result = await service.fuse(make_query(), results)
    q_ids = [e.evidence_id for e in result.evidence]
    assert q_ids == ["EV-Q1", "EV-Q2"]


async def test_production_local_order_preserved() -> None:
    service = make_service()
    ev1 = make_evidence("EV-P1", source_type=EvidenceSourceType.PRODUCTION, source_kind=SourceKind.DEMO_FACTORY, source_id="PO-001")
    ev2 = make_evidence("EV-P2", source_type=EvidenceSourceType.PRODUCTION, source_kind=SourceKind.DEMO_FACTORY, source_id="PO-002")
    results = [make_agent_result(AgentName.PRODUCTION, evidence=[ev1, ev2])]
    result = await service.fuse(make_query(), results)
    p_ids = [e.evidence_id for e in result.evidence]
    assert p_ids == ["EV-P1", "EV-P2"]


async def test_evidence_objects_preserved_without_mutation() -> None:
    service = make_service()
    ev = make_evidence("EV-001", title="Original", content="Original content")
    original_dump = ev.model_dump()
    results = [make_agent_result(evidence=[ev])]
    await service.fuse(make_query(), results)
    assert ev.model_dump() == original_dump


async def test_retrieval_score_preserved() -> None:
    service = make_service()
    ev = make_evidence("EV-001", retrieval_score=0.85)
    results = [make_agent_result(evidence=[ev])]
    result = await service.fuse(make_query(), results)
    assert result.evidence[0].retrieval_score == 0.85


async def test_decision_score_preserved() -> None:
    service = make_service()
    ev = make_evidence("EV-001", decision_score=None)
    results = [make_agent_result(evidence=[ev])]
    result = await service.fuse(make_query(), results)
    assert result.evidence[0].decision_score is None


async def test_document_retrieval_score_not_compared_to_structured() -> None:
    service = make_service()
    doc_ev = make_evidence("EV-D1", retrieval_score=0.9)
    mnt_ev = make_evidence("EV-M1", source_type=EvidenceSourceType.MAINTENANCE, source_kind=SourceKind.DEMO_FACTORY, retrieval_score=None)
    results = [
        make_agent_result(AgentName.DOCUMENT, evidence=[doc_ev]),
        make_agent_result(AgentName.MAINTENANCE, evidence=[mnt_ev]),
    ]
    result = await service.fuse(make_query(), results)
    assert result.evidence[0].retrieval_score == 0.9
    assert result.evidence[1].retrieval_score is None


async def test_identical_duplicate_evidence_id_emitted_once() -> None:
    service = make_service()
    ev1 = make_evidence("EV-DUP")
    ev2 = make_evidence("EV-DUP")
    results = [
        make_agent_result(AgentName.DOCUMENT, evidence=[ev1]),
        make_agent_result(AgentName.DOCUMENT, evidence=[ev2]),
    ]
    result = await service.fuse(make_query(), results)
    assert len(result.evidence) == 1
    assert result.metadata["duplicate_count"] == 1


async def test_same_evidence_id_differing_payload_creates_conflict() -> None:
    service = make_service()
    ev1 = make_evidence("EV-DUP", content="Content A")
    ev2 = make_evidence("EV-DUP", content="Content B")
    results = [
        make_agent_result(AgentName.DOCUMENT, evidence=[ev1]),
        make_agent_result(AgentName.DOCUMENT, evidence=[ev2]),
    ]
    result = await service.fuse(make_query(), results)
    assert len(result.conflicts) == 1
    assert result.conflicts[0].conflict_type == "factual_payload_mismatch"


async def test_same_provenance_identity_identical_payload_deduplicates() -> None:
    service = make_service()
    ev1 = make_evidence("EV-001", source_id="REC-001", record_id="REC-001")
    ev2 = make_evidence("EV-002", source_id="REC-001", record_id="REC-001")
    results = [
        make_agent_result(AgentName.QUALITY, evidence=[ev1]),
        make_agent_result(AgentName.PRODUCTION, evidence=[ev2]),
    ]
    result = await service.fuse(make_query(), results)
    assert len(result.evidence) == 1


async def test_same_provenance_identity_differing_payload_creates_conflict() -> None:
    service = make_service()
    ev1 = make_evidence("EV-001", source_id="REC-001", record_id="REC-001", machine_id="CNC-05")
    ev2 = make_evidence("EV-002", source_id="REC-001", record_id="REC-001", machine_id="CNC-03")
    results = [
        make_agent_result(AgentName.QUALITY, evidence=[ev1]),
        make_agent_result(AgentName.PRODUCTION, evidence=[ev2]),
    ]
    result = await service.fuse(make_query(), results)
    assert len(result.conflicts) >= 1


async def test_different_record_ids_identical_text_not_deduplicated() -> None:
    service = make_service()
    ev1 = make_evidence("EV-001", source_id="ALM-001", record_id="ALM-001", content="Same text")
    ev2 = make_evidence("EV-002", source_id="ALM-002", record_id="ALM-002", content="Same text")
    results = [make_agent_result(AgentName.MAINTENANCE, evidence=[ev1, ev2])]
    result = await service.fuse(make_query(), results)
    assert len(result.evidence) == 2


async def test_aggregate_and_raw_not_deduplicated() -> None:
    service = make_service()
    raw = make_evidence("EV-RAW", source_id="ALM-001", record_id="ALM-001")
    agg = make_evidence("EV-AGG", source_id="ALARM-SUMMARY-CNC-05-ALM-001-abc123", record_id=None)
    results = [make_agent_result(AgentName.MAINTENANCE, evidence=[raw, agg])]
    result = await service.fuse(make_query(), results)
    assert len(result.evidence) == 2


async def test_different_document_chunks_not_deduplicated() -> None:
    service = make_service()
    ev1 = make_evidence("EV-D1", chunk_id="CHUNK-001", page_start=1, page_end=5, source_id="DOC-001", record_id="DOC-001")
    ev2 = make_evidence("EV-D2", chunk_id="CHUNK-002", page_start=6, page_end=10, source_id="DOC-002", record_id="DOC-002")
    results = [make_agent_result(AgentName.DOCUMENT, evidence=[ev1, ev2])]
    result = await service.fuse(make_query(), results)
    assert len(result.evidence) == 2


async def test_same_alarm_description_different_ids_preserved() -> None:
    service = make_service()
    ev1 = make_evidence("EV-A1", source_id="ALM-001", record_id="ALM-001", content="Spindle overheat")
    ev2 = make_evidence("EV-A2", source_id="ALM-002", record_id="ALM-002", content="Spindle overheat")
    results = [make_agent_result(AgentName.MAINTENANCE, evidence=[ev1, ev2])]
    result = await service.fuse(make_query(), results)
    assert len(result.evidence) == 2


async def test_quality_pass_fail_different_inspections_not_conflict() -> None:
    service = make_service()
    ev1 = make_evidence("EV-Q1", source_id="QI-001", record_id="QI-001", content="PASS")
    ev2 = make_evidence("EV-Q2", source_id="QI-002", record_id="QI-002", content="FAIL")
    results = [make_agent_result(AgentName.QUALITY, evidence=[ev1, ev2])]
    result = await service.fuse(make_query(), results)
    assert len(result.conflicts) == 0


async def test_different_telemetry_periods_not_conflicts() -> None:
    service = make_service()
    ev1 = make_evidence("EV-T1", source_id="TEL-SUMMARY-001", record_id=None, observed_at=datetime(2026, 9, 1))
    ev2 = make_evidence("EV-T2", source_id="TEL-SUMMARY-002", record_id=None, observed_at=datetime(2026, 9, 15))
    results = [make_agent_result(AgentName.MAINTENANCE, evidence=[ev1, ev2])]
    result = await service.fuse(make_query(), results)
    assert len(result.conflicts) == 0


async def test_different_production_orders_not_conflicts() -> None:
    service = make_service()
    ev1 = make_evidence("EV-P1", source_id="PO-001", record_id="PO-001")
    ev2 = make_evidence("EV-P2", source_id="PO-002", record_id="PO-002")
    results = [make_agent_result(AgentName.PRODUCTION, evidence=[ev1, ev2])]
    result = await service.fuse(make_query(), results)
    assert len(result.conflicts) == 0


async def test_conflict_id_deterministic() -> None:
    service = make_service()
    ev1 = make_evidence("EV-DUP", content="A")
    ev2 = make_evidence("EV-DUP", content="B")
    results = [make_agent_result(AgentName.DOCUMENT, evidence=[ev1, ev2])]
    r1 = await service.fuse(make_query(), results)
    r2 = await service.fuse(make_query(), results)
    assert r1.conflicts[0].conflict_id == r2.conflicts[0].conflict_id


async def test_conflict_order_deterministic() -> None:
    service = make_service()
    ev1 = make_evidence("EV-DUP1", content="A")
    ev2 = make_evidence("EV-DUP1", content="B")
    ev3 = make_evidence("EV-DUP2", content="C")
    ev4 = make_evidence("EV-DUP2", content="D")
    results = [make_agent_result(AgentName.DOCUMENT, evidence=[ev1, ev2, ev3, ev4])]
    r1 = await service.fuse(make_query(), results)
    r2 = await service.fuse(make_query(), results)
    ids1 = [c.conflict_id for c in r1.conflicts]
    ids2 = [c.conflict_id for c in r2.conflicts]
    assert ids1 == ids2


async def test_evidence_available_when_conflict_exists() -> None:
    service = make_service()
    ev1 = make_evidence("EV-DUP", content="A")
    ev2 = make_evidence("EV-DUP", content="B")
    results = [make_agent_result(AgentName.DOCUMENT, evidence=[ev1, ev2])]
    result = await service.fuse(make_query(), results)
    assert len(result.conflicts) == 1
    assert len(result.evidence) >= 1


async def test_partial_agent_result_evidence_preserved_with_errors() -> None:
    service = make_service()
    ev = make_evidence("EV-001")
    results = [make_agent_result(evidence=[ev], errors=["partial failure"])]
    result = await service.fuse(make_query(), results)
    assert len(result.evidence) == 1
    assert len(result.warnings) > 0


async def test_zero_evidence_agent_result_no_fabrication() -> None:
    service = make_service()
    results = [make_agent_result(AgentName.DOCUMENT, evidence=[])]
    result = await service.fuse(make_query(), results)
    assert result.evidence == []


async def test_agent_result_warnings_not_become_evidence() -> None:
    service = make_service()
    results = [make_agent_result(warnings=["some warning"])]
    result = await service.fuse(make_query(), results)
    assert result.evidence == []
    assert len(result.warnings) > 0


async def test_agent_result_errors_not_become_evidence() -> None:
    service = make_service()
    results = [make_agent_result(errors=["some error"])]
    result = await service.fuse(make_query(), results)
    assert result.evidence == []


async def test_metadata_counts_accurate() -> None:
    service = make_service()
    ev1 = make_evidence("EV-001", source_id="DOC-001")
    ev2 = make_evidence("EV-002", source_id="DOC-002")
    results = [make_agent_result(AgentName.DOCUMENT, evidence=[ev1, ev2])]
    result = await service.fuse(make_query(), results)
    assert result.metadata["agent_result_count"] == 1
    assert result.metadata["evidence_input_count"] == 2
    assert result.metadata["evidence_output_count"] == 2
    assert result.metadata["duplicate_count"] == 0
    assert result.metadata["conflict_count"] == 0


async def test_input_ordering_does_not_change_output() -> None:
    service = make_service()
    ev_d = make_evidence("EV-D1")
    ev_m = make_evidence("EV-M1", source_type=EvidenceSourceType.MAINTENANCE, source_kind=SourceKind.DEMO_FACTORY)
    r1 = await service.fuse(make_query(), [
        make_agent_result(AgentName.DOCUMENT, evidence=[ev_d]),
        make_agent_result(AgentName.MAINTENANCE, evidence=[ev_m]),
    ])
    r2 = await service.fuse(make_query(), [
        make_agent_result(AgentName.MAINTENANCE, evidence=[ev_m]),
        make_agent_result(AgentName.DOCUMENT, evidence=[ev_d]),
    ])
    assert [e.evidence_id for e in r1.evidence] == [e.evidence_id for e in r2.evidence]


async def test_repeated_fusion_idempotent() -> None:
    service = make_service()
    ev1 = make_evidence("EV-001")
    ev2 = make_evidence("EV-002")
    results = [make_agent_result(AgentName.DOCUMENT, evidence=[ev1, ev2])]
    r1 = await service.fuse(make_query(), results)
    r2 = await service.fuse(make_query(), results)
    assert [e.evidence_id for e in r1.evidence] == [e.evidence_id for e in r2.evidence]
    assert r1.metadata == r2.metadata


async def test_input_agent_results_not_mutated() -> None:
    service = make_service()
    ev = make_evidence("EV-001")
    results = [make_agent_result(evidence=[ev])]
    original_len = len(results[0].evidence)
    await service.fuse(make_query(), results)
    assert len(results[0].evidence) == original_len


async def test_input_evidence_not_mutated() -> None:
    service = make_service()
    ev = make_evidence("EV-001", title="Original", content="Original")
    original_dump = ev.model_dump()
    results = [make_agent_result(evidence=[ev])]
    await service.fuse(make_query(), results)
    assert ev.model_dump() == original_dump


async def test_no_jev_calls() -> None:
    service = make_service()
    assert not hasattr(service, "_jev_client")
    assert not hasattr(service, "_decision_engine")


async def test_no_decision_engine_calls() -> None:
    service = make_service()
    assert not hasattr(service, "_decision_engine")


async def test_no_agent_execution() -> None:
    service = make_service()
    assert not hasattr(service, "_document_agent")
    assert not hasattr(service, "_maintenance_agent")
    assert not hasattr(service, "_quality_agent")
    assert not hasattr(service, "_production_agent")


async def test_no_repository_access() -> None:
    service = make_service()
    assert not hasattr(service, "_repository")


async def test_no_db_access() -> None:
    service = make_service()
    assert not hasattr(service, "_db")
    assert not hasattr(service, "_database")


async def test_no_rag_access() -> None:
    service = make_service()
    assert not hasattr(service, "_retriever")
    assert not hasattr(service, "_rag")


async def test_no_hidden_ground_truth() -> None:
    service = make_service()
    results = [make_agent_result(evidence=[make_evidence("EV-001")])]
    result = await service.fuse(make_query(), results)
    assert "hidden_simulated_cause" not in str(result.metadata)
    assert "demo_cases" not in str(result.metadata)


async def test_no_llm_dependencies() -> None:
    service = make_service()
    assert not hasattr(service, "_llm_client")
    assert not hasattr(service, "_gemini")
    assert not hasattr(service, "_openai")


async def test_no_arbitrary_evidence_scoring() -> None:
    service = make_service()
    ev = make_evidence("EV-001", retrieval_score=0.5)
    results = [make_agent_result(evidence=[ev])]
    result = await service.fuse(make_query(), results)
    assert result.evidence[0].retrieval_score == 0.5
    assert "fusion_score" not in result.metadata
    assert "importance_score" not in result.metadata


async def test_no_semantic_contradiction_parsing() -> None:
    service = make_service()
    ev1 = make_evidence("EV-001", source_id="QI-001", record_id="QI-001", content="PASS")
    ev2 = make_evidence("EV-002", source_id="QI-002", record_id="QI-002", content="FAIL")
    results = [make_agent_result(AgentName.QUALITY, evidence=[ev1, ev2])]
    result = await service.fuse(make_query(), results)
    assert len(result.conflicts) == 0


async def test_no_nondeterministic_ids() -> None:
    service = make_service()
    ev1 = make_evidence("EV-DUP", content="A")
    ev2 = make_evidence("EV-DUP", content="B")
    results = [make_agent_result(AgentName.DOCUMENT, evidence=[ev1, ev2])]
    r1 = await service.fuse(make_query(), results)
    r2 = await service.fuse(make_query(), results)
    assert r1.conflicts[0].conflict_id == r2.conflicts[0].conflict_id
    assert "generated_at" not in r1.metadata


def test_static_architecture_boundary() -> None:
    source = (Path(__file__).resolve().parents[2] / "app" / "fusion" / "service.py").read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in (
        "jevdecisionengine",
        "decisionengine",
        "typesafe_sdk",
        "documentagent",
        "maintenanceagent",
        "qualityagent",
        "productionagent",
        "app.repositories",
        "app.db",
        "app.rag",
        "gemini",
        "openai",
        "groq",
        "langgraph",
        "sqlite3",
        "aiosqlite",
    ):
        assert forbidden not in lowered, f"forbidden reference: {forbidden}"


def test_no_direct_sql() -> None:
    source = (Path(__file__).resolve().parents[2] / "app" / "fusion" / "service.py").read_text(encoding="utf-8")
    for keyword in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert keyword not in source


def test_frozen_contract_return_types() -> None:
    service = make_service()
    assert service.__class__ is DeterministicEvidenceFusionService


async def test_cross_domain_bundle_composition() -> None:
    service = make_service()
    doc_ev = make_evidence("EV-D1", source_type=EvidenceSourceType.MANUAL, source_id="DOC-001")
    mnt_ev = make_evidence("EV-M1", source_type=EvidenceSourceType.MAINTENANCE, source_kind=SourceKind.DEMO_FACTORY, source_id="MNT-001")
    alarm_ev = make_evidence("EV-A1", source_type=EvidenceSourceType.ALARM, source_kind=SourceKind.DEMO_FACTORY, source_id="ALM-001")
    tel_ev = make_evidence("EV-T1", source_type=EvidenceSourceType.TELEMETRY, source_kind=SourceKind.DEMO_FACTORY, source_id="TEL-001")
    qual_ev = make_evidence("EV-Q1", source_type=EvidenceSourceType.QUALITY, source_kind=SourceKind.DEMO_FACTORY, source_id="QI-001")
    prod_ev = make_evidence("EV-P1", source_type=EvidenceSourceType.PRODUCTION, source_kind=SourceKind.DEMO_FACTORY, source_id="PO-001")
    results = [
        make_agent_result(AgentName.DOCUMENT, evidence=[doc_ev]),
        make_agent_result(AgentName.MAINTENANCE, evidence=[mnt_ev, alarm_ev, tel_ev]),
        make_agent_result(AgentName.QUALITY, evidence=[qual_ev]),
        make_agent_result(AgentName.PRODUCTION, evidence=[prod_ev]),
    ]
    result = await service.fuse(make_query(), results)
    assert len(result.evidence) == 6
    assert len(result.conflicts) == 0
    types = [e.source_type for e in result.evidence]
    assert types == [
        EvidenceSourceType.MANUAL,
        EvidenceSourceType.MAINTENANCE,
        EvidenceSourceType.ALARM,
        EvidenceSourceType.TELEMETRY,
        EvidenceSourceType.QUALITY,
        EvidenceSourceType.PRODUCTION,
    ]


async def test_conflict_test_case() -> None:
    service = make_service()
    ev1 = make_evidence("EV-DUP", source_id="QI-001", record_id="QI-001", content="measured=10.1")
    ev2 = make_evidence("EV-DUP", source_id="QI-001", record_id="QI-001", content="measured=10.5")
    results = [make_agent_result(AgentName.QUALITY, evidence=[ev1, ev2])]
    result = await service.fuse(make_query(), results)
    assert len(result.conflicts) == 1
    assert result.conflicts[0].severity == RiskLevel.MEDIUM
    assert result.conflicts[0].resolved is False
