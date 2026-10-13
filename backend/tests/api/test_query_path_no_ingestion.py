from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi.testclient import TestClient

from app.contracts.agents import AgentResult
from app.contracts.enums import AgentName, Domain, EvidenceSourceType, ProviderStatus, ReviewAction, RiskLevel, SourceKind
from app.contracts.evidence import Evidence, EvidenceProvenance
from app.contracts.fusion import EvidenceBundle
from app.contracts.query import QueryRequest
from app.contracts.reasoning import ReasoningResult
from app.contracts.review import ReviewDecision
from app.contracts.routing import RoutingDecision
from app.core.config import Settings
from app.core.exceptions import ProviderUnavailableError
from app.main import create_app
from app.orchestration.workflow import ManufacturaIQOrchestrator
from app.reasoning.gemini import GeminiReasoner


class FakeDecisionEngine:
    async def route(self, query: QueryRequest) -> RoutingDecision:
        return RoutingDecision(
            query_id=query.query_id,
            intent=Domain.MAINTENANCE,
            selected_agents=[AgentName.DOCUMENT],
            needs_clarification=False,
            risk_level=RiskLevel.LOW,
            provider_status=ProviderStatus.SUCCESS,
        )

    async def review(self, query: QueryRequest, bundle: EvidenceBundle, reasoning: ReasoningResult) -> ReviewDecision:
        return ReviewDecision(
            query_id=query.query_id,
            action=ReviewAction.HUMAN_REVIEW,
            reasons=["fake review"],
            provider_status=ProviderStatus.SUCCESS,
        )


class FakeDocumentAgent:
    async def run(self, query: QueryRequest):
        return AgentResult(agent_name=AgentName.DOCUMENT, query_id=query.query_id, evidence=[], metadata={})


class FakeFusion:
    async def fuse(self, query: QueryRequest, results: list[Any]) -> EvidenceBundle:
        return EvidenceBundle(query_id=query.query_id, evidence=[])


class FakeReasoner:
    async def reason(self, query: QueryRequest, evidence: EvidenceBundle) -> ReasoningResult:
        return ReasoningResult(
            query_id=query.query_id,
            observations=[],
            possible_causes=[],
            recommended_checks=[],
            missing_information=["No evidence."],
            citations=[],
            raw_answer="Grounded reasoning unavailable: No evidence.",
            provider_status=ProviderStatus.UNAVAILABLE,
        )


def test_normal_query_path_does_not_invoke_pdf_extraction_chunking_or_ingestion(monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError("query path must not invoke document ingestion work")

    monkeypatch.setattr("app.documents.ingestion.extract_pages", fail)
    monkeypatch.setattr("app.documents.ingestion.build_document_chunks", fail)
    monkeypatch.setattr("app.documents.ingestion.DocumentIngestionService.ingest_pdf", fail)

    orchestrator = ManufacturaIQOrchestrator(
        FakeDecisionEngine(),
        {AgentName.DOCUMENT: FakeDocumentAgent()},
        FakeFusion(),
        FakeReasoner(),
    )
    app = create_app(orchestrator=orchestrator)
    with TestClient(app) as client:
        response = client.post("/api/query", json={"query": "normal document query"})

    assert response.status_code == 200
    assert response.json()["status"] == "human_review"


class SleepingOrchestrator:
    async def run(self, query: QueryRequest):
        await asyncio.sleep(1.0)
        return {"query_id": query.query_id}


def test_total_query_deadline_returns_controlled_error_quickly():
    app = create_app(
        orchestrator=SleepingOrchestrator(),
        settings=Settings(_env_file=None, query_total_timeout_seconds=0.1),
    )
    with TestClient(app) as client:
        started = time.perf_counter()
        response = client.post("/api/query", json={"query": "slow query"})
        elapsed = time.perf_counter() - started

    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "query deadline exceeded"
    assert elapsed < 0.5


def _document_evidence() -> Evidence:
    return Evidence(
        evidence_id="EV-TIMEOUT-1",
        source_type=EvidenceSourceType.MANUAL,
        provenance=EvidenceProvenance(
            source_kind=SourceKind.DOCUMENT,
            source_dataset="manufacturaiq_document_corpus",
            source_id="doc-1",
            document_id="doc-1",
            chunk_id="chunk-1",
        ),
        title="Haas spindle warm-up",
        content="Run spindle warm-up before high-speed operation.",
    )


class EvidenceDocumentAgent:
    async def run(self, query: QueryRequest):
        return AgentResult(
            agent_name=AgentName.DOCUMENT,
            query_id=query.query_id,
            evidence=[_document_evidence()],
            latency_ms=1.0,
        )


class EvidenceFusion:
    async def fuse(self, query: QueryRequest, results: list[Any]) -> EvidenceBundle:
        evidence = []
        for result in results:
            evidence.extend(result.evidence)
        return EvidenceBundle(query_id=query.query_id, evidence=evidence)


class SleepingGeminiClient:
    @property
    def aio(self):
        return self

    @property
    def interactions(self):
        return self

    async def create(self, **_kwargs):
        await asyncio.sleep(1.0)
        return None


class FailingFallbackGeminiClient:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def aio(self):
        return self

    @property
    def interactions(self):
        return self

    async def create(self, **_kwargs):
        self.calls += 1
        raise ProviderUnavailableError("Error code: 503 - provider overloaded")


def test_evidence_survives_gemini_timeout_to_api_response():
    settings = Settings(
        _env_file=None,
        gemini_api_key="test-key",
        gemini_total_budget_seconds=0.1,
        gemini_request_timeout_seconds=0.1,
        gemini_max_attempts=1,
        query_total_timeout_seconds=1.0,
    )
    orchestrator = ManufacturaIQOrchestrator(
        FakeDecisionEngine(),
        {AgentName.DOCUMENT: EvidenceDocumentAgent()},
        EvidenceFusion(),
        GeminiReasoner(SleepingGeminiClient(), settings=settings),
    )
    app = create_app(orchestrator=orchestrator, settings=settings)
    with TestClient(app) as client:
        response = client.post("/api/query", json={"query": "slow reasoning"})

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "human_review"
    assert body["reasoning"]["provider_status"] == ProviderStatus.UNAVAILABLE
    assert body["review"]["action"] == ReviewAction.HUMAN_REVIEW
    assert body["evidence"]["evidence"][0]["evidence_id"] == "EV-TIMEOUT-1"


def test_evidence_survives_both_gemini_models_failing_to_api_response():
    settings = Settings(
        _env_file=None,
        gemini_api_key="test-key",
        gemini_total_budget_seconds=0.3,
        gemini_request_timeout_seconds=0.2,
        gemini_primary_timeout_seconds=0.1,
        gemini_retry_backoff_seconds=0,
        query_total_timeout_seconds=1.0,
    )
    provider = FailingFallbackGeminiClient()
    orchestrator = ManufacturaIQOrchestrator(
        FakeDecisionEngine(),
        {AgentName.DOCUMENT: EvidenceDocumentAgent()},
        EvidenceFusion(),
        GeminiReasoner(provider, settings=settings),
    )
    app = create_app(orchestrator=orchestrator, settings=settings)
    with TestClient(app) as client:
        response = client.post("/api/query", json={"query": "both models fail"})

    body = response.json()
    assert response.status_code == 200
    assert provider.calls == 2
    assert body["status"] == "human_review"
    assert body["reasoning"]["provider_status"] == ProviderStatus.UNAVAILABLE
    assert body["review"]["action"] == ReviewAction.HUMAN_REVIEW
    assert body["evidence"]["evidence"][0]["evidence_id"] == "EV-TIMEOUT-1"
