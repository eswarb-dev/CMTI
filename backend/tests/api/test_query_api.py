from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.contracts.enums import AgentName, Domain, EvidenceSourceType, ProviderStatus, ReviewAction, RiskLevel, SourceKind
from app.contracts.evidence import Evidence, EvidenceProvenance
from app.contracts.fusion import EvidenceBundle, EvidenceConflict
from app.contracts.query import QueryRequest
from app.contracts.reasoning import EvidenceCitation, ReasoningResult
from app.contracts.review import ReviewDecision
from app.contracts.routing import RoutingDecision
from app.main import create_app


class FakeOrchestrator:
    def __init__(self, mode: str = "pass") -> None:
        self.mode = mode
        self.calls: list[QueryRequest] = []

    async def run(self, query: QueryRequest) -> dict[str, Any]:
        self.calls.append(query)
        if self.mode == "runtime_error":
            raise RuntimeError("secret traceback D:\\CMTI\\backend\\token")
        if self.mode == "clarify":
            routing = make_routing(query, needs_clarification=True)
            return {"query_id": query.query_id, "routing_decision": routing, "agent_results": []}
        action = ReviewAction.HUMAN_REVIEW if self.mode == "human_review" else ReviewAction.PASS
        return make_workflow_result(query, action)


class EnterTrackingOrchestrator:
    def __init__(self) -> None:
        self.entered = 0
        self.release = asyncio.Event()
        self.queries: list[str] = []

    async def run(self, query: QueryRequest) -> dict[str, Any]:
        self.entered += 1
        self.queries.append(query.query)
        if self.entered == 2:
            self.release.set()
        await self.release.wait()
        return make_workflow_result(query, ReviewAction.PASS)


def make_routing(query: QueryRequest, *, needs_clarification: bool = False) -> RoutingDecision:
    return RoutingDecision(
        query_id=query.query_id,
        intent=Domain.MAINTENANCE,
        selected_agents=[] if needs_clarification else [AgentName.MAINTENANCE],
        needs_clarification=needs_clarification,
        clarification_reason="Please provide a machine id." if needs_clarification else None,
        risk_level=RiskLevel.LOW,
        confidence=0.82,
        provider_status=ProviderStatus.SUCCESS,
        decision_metadata={"source": "fake"},
    )


def make_evidence(query: QueryRequest) -> Evidence:
    return Evidence(
        evidence_id=f"{query.query_id}:ev1",
        source_type=EvidenceSourceType.MAINTENANCE,
        provenance=EvidenceProvenance(
            source_kind=SourceKind.DEMO_FACTORY,
            source_dataset="demo_factory",
            source_id="maintenance:1",
            record_id="maint-1",
        ),
        machine_id=query.machine_id,
        product_id=query.product_id,
        batch_id=query.batch_id,
        title="Maintenance evidence",
        content="Synthetic maintenance evidence.",
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        retrieval_score=None,
        decision_score=None,
        metadata={"visible": True},
    )


def make_workflow_result(query: QueryRequest, action: ReviewAction) -> dict[str, Any]:
    evidence = make_evidence(query)
    bundle = EvidenceBundle(
        query_id=query.query_id,
        evidence=[evidence],
        conflicts=[
            EvidenceConflict(
                conflict_id="conflict-1",
                evidence_ids=[evidence.evidence_id],
                conflict_type="example",
                description="Synthetic conflict placeholder.",
                severity=RiskLevel.LOW,
                resolved=False,
            )
        ],
        missing_information=["operator note"],
        warnings=["low evidence"],
        metadata={"count": 1},
    )
    reasoning = ReasoningResult(
        query_id=query.query_id,
        observations=["Observation grounded in evidence."],
        possible_causes=[],
        recommended_checks=["Check maintenance log."],
        missing_information=["operator note"],
        citations=[EvidenceCitation(evidence_id=evidence.evidence_id, label="E1")],
        raw_answer="Grounded answer.",
        provider_status=ProviderStatus.SUCCESS,
        model="fake-reasoner",
        metadata={"reasoned": True},
    )
    review = ReviewDecision(
        query_id=query.query_id,
        action=action,
        reasons=["review reason"],
        confidence=0.9,
        provider_status=ProviderStatus.SUCCESS,
        metadata={"reviewed": True},
    )
    return {
        "query_id": query.query_id,
        "routing_decision": make_routing(query),
        "agent_results": [],
        "evidence_bundle": bundle,
        "reasoning_result": reasoning,
        "review_decision": review,
    }


def post_query(client: TestClient, payload: dict[str, Any]) -> Any:
    return client.post("/api/query", json=payload)


def test_valid_minimal_query_generates_query_id_and_calls_orchestrator_once():
    orchestrator = FakeOrchestrator()
    with TestClient(create_app(orchestrator=orchestrator)) as client:
        response = post_query(client, {"query": "Investigate rejects."})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pass"
    assert body["query_id"]
    assert len(orchestrator.calls) == 1
    assert orchestrator.calls[0].query_id == body["query_id"]
    assert orchestrator.calls[0].query == "Investigate rejects."


def test_machine_product_batch_and_time_mapping():
    orchestrator = FakeOrchestrator()
    payload = {
        "query": "Investigate supplied scope.",
        "machine_id": "CNC-05",
        "product_id": "SHAFT-A",
        "batch_id": "BATCH-01",
        "time_start": "2026-01-01T00:00:00Z",
        "time_end": "2026-01-02T00:00:00Z",
    }
    with TestClient(create_app(orchestrator=orchestrator)) as client:
        response = post_query(client, payload)

    assert response.status_code == 200
    query = orchestrator.calls[0]
    assert query.machine_id == "CNC-05"
    assert query.product_id == "SHAFT-A"
    assert query.batch_id == "BATCH-01"
    assert query.time_start is not None
    assert query.time_end is not None


def test_allowed_document_context_maps_to_user_context():
    orchestrator = FakeOrchestrator()
    payload = {
        "query": "Find the manual section.",
        "document_context": {
            "document_type": "manual",
            "manufacturer": "Siemens",
            "machine_family": "lathe",
            "model": "840D",
            "document_id": "DOC-1",
            "language": "en",
        },
    }
    with TestClient(create_app(orchestrator=orchestrator)) as client:
        response = post_query(client, payload)

    assert response.status_code == 200
    assert orchestrator.calls[0].user_context == payload["document_context"]


def test_arbitrary_context_and_unknown_fields_are_rejected():
    with TestClient(create_app(orchestrator=FakeOrchestrator())) as client:
        response = post_query(
            client,
            {
                "query": "Find docs.",
                "user_context": {"hidden_simulated_cause": "nope"},
            },
        )
        nested = post_query(
            client,
            {
                "query": "Find docs.",
                "document_context": {"document_type": "manual", "unexpected": "nope"},
            },
        )

    assert response.status_code == 422
    assert nested.status_code == 422


def test_route_handler_does_not_call_pipeline_components_directly():
    orchestrator = FakeOrchestrator()
    with TestClient(create_app(orchestrator=orchestrator)) as client:
        response = post_query(client, {"query": "Run through orchestrator only."})

    assert response.status_code == 200
    assert len(orchestrator.calls) == 1


def test_clarification_returns_http_200_without_downstream_outputs():
    orchestrator = FakeOrchestrator(mode="clarify")
    with TestClient(create_app(orchestrator=orchestrator)) as client:
        response = post_query(client, {"query": "Ambiguous request."})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "needs_clarification"
    assert body["routing"]["clarification_reason"] == "Please provide a machine id."
    assert body["evidence"] is None
    assert body["reasoning"] is None
    assert body["review"] is None


def test_pass_response_preserves_reasoning_review_evidence_warnings_and_conflicts():
    with TestClient(create_app(orchestrator=FakeOrchestrator())) as client:
        response = post_query(client, {"query": "Investigate rejects."})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pass"
    assert body["reasoning"]["raw_answer"] == "Grounded answer."
    assert body["review"]["action"] == "PASS"
    assert body["evidence"]["warnings"] == ["low evidence"]
    assert body["evidence"]["conflicts"][0]["conflict_id"] == "conflict-1"


def test_human_review_response_is_not_server_failure():
    with TestClient(create_app(orchestrator=FakeOrchestrator(mode="human_review"))) as client:
        response = post_query(client, {"query": "Needs a review."})

    assert response.status_code == 200
    assert response.json()["status"] == "human_review"
    assert response.json()["review"]["action"] == "HUMAN_REVIEW"


@pytest.mark.parametrize(
    "payload",
    [
        {"query": "   "},
        {"query": "Bad time.", "time_start": "2026-01-02T00:00:00Z", "time_end": "2026-01-01T00:00:00Z"},
        {"query": "Bad datetime.", "time_start": "not-a-date"},
        {"query": "Unknown.", "unknown": "field"},
    ],
)
def test_invalid_requests_use_fastapi_validation(payload: dict[str, Any]):
    with TestClient(create_app(orchestrator=FakeOrchestrator())) as client:
        response = post_query(client, payload)

    assert response.status_code == 422


def test_unexpected_orchestrator_error_returns_sanitized_500():
    with TestClient(create_app(orchestrator=FakeOrchestrator(mode="runtime_error"))) as client:
        response = post_query(client, {"query": "Explode safely."})

    assert response.status_code == 500
    body_text = response.text
    assert "internal server error" in body_text
    assert "Traceback" not in body_text
    assert "D:\\CMTI" not in body_text
    assert "secret" not in body_text


@pytest.mark.asyncio
async def test_concurrent_requests_share_orchestrator_without_state_leakage():
    orchestrator = EnterTrackingOrchestrator()
    app = create_app(orchestrator=orchestrator)
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            left, right = await asyncio.gather(
                client.post("/api/query", json={"query": "First query."}),
                client.post("/api/query", json={"query": "Second query."}),
            )

    assert left.status_code == 200
    assert right.status_code == 200
    assert orchestrator.entered == 2
    assert {left.json()["query_id"], right.json()["query_id"]}
    assert left.json()["query_id"] != right.json()["query_id"]
    assert orchestrator.queries == ["First query.", "Second query."]

