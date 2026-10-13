from __future__ import annotations

import asyncio

from app.contracts.agents import AgentResult
from app.contracts.enums import AgentName, Domain, ProviderStatus, ReviewAction, RiskLevel
from app.contracts.fusion import EvidenceBundle
from app.contracts.query import QueryRequest
from app.contracts.reasoning import ReasoningResult
from app.contracts.review import ReviewDecision
from app.contracts.routing import RoutingDecision
from app.protocols import Agent, DecisionEngine, DocumentRetriever, EvidenceFusionService, Reasoner, ReviewGate
from tests.fixtures.examples import document_evidence


class FakeAgent:
    async def run(self, query: QueryRequest) -> AgentResult:
        return AgentResult(agent_name=AgentName.DOCUMENT, query_id=query.query_id, evidence=[document_evidence()])


class FakeDocumentRetriever:
    async def retrieve(self, query: QueryRequest, top_k: int = 10):
        return [document_evidence()][:top_k]


class FakeDecisionEngine:
    async def route(self, query: QueryRequest) -> RoutingDecision:
        return RoutingDecision(
            query_id=query.query_id,
            intent=Domain.DOCUMENTATION,
            selected_agents=[AgentName.DOCUMENT],
            needs_clarification=False,
            risk_level=RiskLevel.LOW,
            provider_status=ProviderStatus.SUCCESS,
        )

    async def score_evidence(self, query: QueryRequest, evidence):
        return evidence

    async def review(self, query: QueryRequest, bundle: EvidenceBundle, reasoning: ReasoningResult) -> ReviewDecision:
        return ReviewDecision(query_id=query.query_id, action=ReviewAction.PASS, provider_status=ProviderStatus.SUCCESS)


class FakeFusionService:
    async def fuse(self, query: QueryRequest, agent_results: list[AgentResult]) -> EvidenceBundle:
        evidence = [item for result in agent_results for item in result.evidence]
        return EvidenceBundle(query_id=query.query_id, evidence=evidence)


class FakeReasoner:
    async def reason(self, query: QueryRequest, evidence: EvidenceBundle) -> ReasoningResult:
        return ReasoningResult(
            query_id=query.query_id,
            observations=["test"],
            possible_causes=[],
            recommended_checks=[],
            missing_information=[],
            citations=[],
            raw_answer="test answer",
            provider_status=ProviderStatus.SUCCESS,
        )


class FakeReviewGate:
    async def evaluate(self, query: QueryRequest, evidence: EvidenceBundle, reasoning: ReasoningResult) -> ReviewDecision:
        return ReviewDecision(query_id=query.query_id, action=ReviewAction.PASS, provider_status=ProviderStatus.SUCCESS)


def test_protocols_can_be_implemented_by_test_doubles() -> None:
    query = QueryRequest(query_id="Q-1", query="Check spindle", user_context={})
    agent: Agent = FakeAgent()
    retriever: DocumentRetriever = FakeDocumentRetriever()
    decision: DecisionEngine = FakeDecisionEngine()
    fusion: EvidenceFusionService = FakeFusionService()
    reasoner: Reasoner = FakeReasoner()
    review_gate: ReviewGate = FakeReviewGate()

    async def run_all() -> None:
        agent_result = await agent.run(query)
        retrieved = await retriever.retrieve(query)
        route = await decision.route(query)
        scored = await decision.score_evidence(query, retrieved)
        bundle = await fusion.fuse(query, [agent_result])
        reasoning = await reasoner.reason(query, bundle)
        review = await review_gate.evaluate(query, bundle, reasoning)
        decision_review = await decision.review(query, bundle, reasoning)
        assert agent_result.evidence
        assert scored
        assert route.selected_agents == [AgentName.DOCUMENT]
        assert review.action is ReviewAction.PASS
        assert decision_review.action is ReviewAction.PASS

    asyncio.run(run_all())

