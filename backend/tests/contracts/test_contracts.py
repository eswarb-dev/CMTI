from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.contracts.agents import AgentResult
from app.contracts.enums import AgentName, Domain, ProviderStatus, ReviewAction, RiskLevel, SourceKind
from app.contracts.evidence import EvidenceProvenance
from app.contracts.fusion import EvidenceBundle, EvidenceConflict
from app.contracts.query import QueryRequest
from app.contracts.reasoning import EvidenceCitation, ReasoningResult
from app.contracts.review import ReviewDecision
from app.contracts.routing import RoutingDecision
from tests.fixtures.examples import document_evidence, structured_evidence


def test_query_request_valid_query() -> None:
    query = QueryRequest(query_id="Q-1", query="  Investigate CNC-05  ", user_context={"role": "engineer"})
    assert query.query == "Investigate CNC-05"


def test_query_request_rejects_empty_query() -> None:
    with pytest.raises(ValidationError):
        QueryRequest(query_id="Q-1", query="   ", user_context={})


def test_query_request_rejects_invalid_time_range() -> None:
    with pytest.raises(ValidationError):
        QueryRequest(
            query_id="Q-1",
            query="Check trend",
            time_start=datetime(2026, 1, 2, tzinfo=timezone.utc),
            time_end=datetime(2026, 1, 1, tzinfo=timezone.utc),
            user_context={},
        )


def test_evidence_document_provenance() -> None:
    evidence = document_evidence()
    assert evidence.provenance.source_kind is SourceKind.DOCUMENT
    assert evidence.provenance.document_id == "DOC-ABCDEF123456"
    assert evidence.provenance.page_start == 120


def test_evidence_structured_provenance() -> None:
    evidence = structured_evidence()
    assert evidence.provenance.source_kind is SourceKind.DEMO_FACTORY
    assert evidence.provenance.record_id == "TEL-000001"
    assert evidence.machine_id == "CNC-05"


def test_page_start_page_end_validation() -> None:
    with pytest.raises(ValidationError):
        EvidenceProvenance(
            source_kind=SourceKind.DOCUMENT,
            source_dataset="docs",
            source_id="DOC-1",
            document_id="DOC-1",
            page_start=5,
            page_end=3,
        )
    with pytest.raises(ValidationError):
        EvidenceProvenance(
            source_kind=SourceKind.DOCUMENT,
            source_dataset="docs",
            source_id="DOC-1",
            page_start=0,
        )


def test_agent_result_serialization() -> None:
    result = AgentResult(agent_name=AgentName.DOCUMENT, query_id="Q-1", evidence=[document_evidence()])
    dumped = result.model_dump()
    assert dumped["agent_name"] is AgentName.DOCUMENT
    assert "DOCUMENT" in result.model_dump_json()


def test_routing_decision_unique_selected_agents() -> None:
    decision = RoutingDecision(
        query_id="Q-1",
        intent=Domain.MULTI_DOMAIN,
        selected_agents=[AgentName.DOCUMENT, AgentName.QUALITY],
        needs_clarification=False,
        risk_level=RiskLevel.MEDIUM,
        provider_status=ProviderStatus.SUCCESS,
    )
    assert decision.selected_agents == [AgentName.DOCUMENT, AgentName.QUALITY]
    with pytest.raises(ValidationError):
        RoutingDecision(
            query_id="Q-1",
            intent=Domain.DOCUMENTATION,
            selected_agents=[AgentName.DOCUMENT, AgentName.DOCUMENT],
            needs_clarification=False,
            risk_level=RiskLevel.LOW,
            provider_status=ProviderStatus.SUCCESS,
        )
    with pytest.raises(ValidationError):
        RoutingDecision(
            query_id="Q-1",
            intent=Domain.UNKNOWN,
            selected_agents=[],
            needs_clarification=True,
            risk_level=RiskLevel.LOW,
            provider_status=ProviderStatus.SUCCESS,
        )


def test_evidence_bundle_and_conflict_serialization() -> None:
    conflict = EvidenceConflict(
        conflict_id="CONFLICT-1",
        evidence_ids=["EV-DOC-001", "EV-TEL-001"],
        conflict_type="timestamp_mismatch",
        description="Example conflict.",
        severity=RiskLevel.MEDIUM,
        resolved=False,
    )
    bundle = EvidenceBundle(
        query_id="Q-1",
        evidence=[document_evidence(), structured_evidence()],
        conflicts=[conflict],
        missing_information=["Need inspection note"],
    )
    assert bundle.model_dump()["conflicts"][0]["severity"] is RiskLevel.MEDIUM
    assert "EV-DOC-001" in bundle.model_dump_json()


def test_reasoning_result_citation_serialization() -> None:
    result = ReasoningResult(
        query_id="Q-1",
        observations=["Observed vibration increase."],
        possible_causes=["Possible imbalance."],
        recommended_checks=["Inspect spindle tooling."],
        missing_information=[],
        citations=[EvidenceCitation(evidence_id="EV-DOC-001", label="manual")],
        raw_answer="Evidence-grounded test answer.",
        provider_status=ProviderStatus.SUCCESS,
        model="test-model",
    )
    assert result.citations[0].evidence_id == "EV-DOC-001"
    assert "SUCCESS" in result.model_dump_json()


def test_review_decision_serialization() -> None:
    review = ReviewDecision(
        query_id="Q-1",
        action=ReviewAction.HUMAN_REVIEW,
        reasons=["High risk."],
        confidence=0.7,
        provider_status=ProviderStatus.FALLBACK,
    )
    assert review.action is ReviewAction.HUMAN_REVIEW
    assert "HUMAN_REVIEW" in review.model_dump_json()


def test_enums_serialize_as_strings() -> None:
    payload = QueryRequest(query_id="Q-1", query="x", user_context={}).model_dump_json()
    assert '"query_id":"Q-1"' in payload
    assert '"source_kind":"DOCUMENT"' in document_evidence().model_dump_json()


def test_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        QueryRequest(query_id="Q-1", query="x", user_context={}, unexpected=True)  # type: ignore[call-arg]

