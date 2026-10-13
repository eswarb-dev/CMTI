from __future__ import annotations

import asyncio
import inspect
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.contracts.agents import AgentResult
from app.contracts.enums import AgentName, ProviderStatus, ReviewAction
from app.contracts.fusion import EvidenceBundle
from app.contracts.query import QueryRequest
from app.contracts.reasoning import EvidenceCitation, ReasoningResult
from app.contracts.review import ReviewDecision
from app.contracts.routing import RoutingDecision
from app.orchestration.workflow import ManufacturaIQOrchestrator, build_manufacturaiq_orchestrator
from app.protocols.agents import Agent
from app.protocols.decision import DecisionEngine
from app.protocols.fusion import EvidenceFusionService
from app.protocols.reasoning import Reasoner


def make_query(**overrides) -> QueryRequest:
    fields: dict = {"query_id": "Q-ORCH-1", "query": "analyze production"}
    fields.update(overrides)
    return QueryRequest(**fields)


def make_agent_result(
    agent_name: AgentName = AgentName.DOCUMENT,
    query_id: str = "Q-ORCH-1",
    evidence: list | None = None,
    errors: list | None = None,
) -> AgentResult:
    return AgentResult(
        agent_name=agent_name,
        query_id=query_id,
        evidence=evidence or [],
        warnings=[],
        errors=errors or [],
    )


def make_routing_decision(
    selected_agents: list[AgentName] | None = None,
    needs_clarification: bool = False,
    query_id: str = "Q-ORCH-1",
) -> RoutingDecision:
    return RoutingDecision(
        query_id=query_id,
        intent="MULTI_DOMAIN" if selected_agents and len(selected_agents) > 1 else "DOCUMENTATION",
        selected_agents=[AgentName.DOCUMENT] if selected_agents is None else selected_agents,
        needs_clarification=needs_clarification,
        clarification_reason="Need clarification" if needs_clarification else None,
        risk_level="LOW",
        provider_status=ProviderStatus.SUCCESS,
    )


def make_reasoning_result(
    query_id: str = "Q-ORCH-1",
    provider_status: ProviderStatus = ProviderStatus.SUCCESS,
) -> ReasoningResult:
    return ReasoningResult(
        query_id=query_id,
        observations=["Observation"],
        possible_causes=["Possible cause"],
        recommended_checks=["Verify condition"],
        citations=[EvidenceCitation(evidence_id="EV-001")],
        raw_answer="Test answer",
        provider_status=provider_status,
    )


def make_review_decision(
    query_id: str = "Q-ORCH-1",
    action: ReviewAction = ReviewAction.PASS,
) -> ReviewDecision:
    return ReviewDecision(
        query_id=query_id,
        action=action,
        reasons=[] if action == ReviewAction.PASS else ["test_reason"],
        provider_status=ProviderStatus.SUCCESS,
    )


def make_bundle(query_id: str = "Q-ORCH-1") -> EvidenceBundle:
    return EvidenceBundle(query_id=query_id)


class FakeAgent:
    def __init__(self, result: AgentResult | None = None, error: Exception | None = None):
        self._result = result
        self._error = error
        self.calls: list = []

    async def run(self, query: QueryRequest) -> AgentResult:
        self.calls.append(query)
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


class FakeDecisionEngine:
    def __init__(self, routing: RoutingDecision | None = None, review: ReviewDecision | None = None):
        self._routing = routing or make_routing_decision()
        self._review = review or make_review_decision()
        self.route_calls: list = []
        self.review_calls: list = []
        self.score_evidence_calls: list = []

    async def route(self, query: QueryRequest) -> RoutingDecision:
        self.route_calls.append(query)
        return self._routing

    async def review(
        self, query: QueryRequest, bundle: EvidenceBundle, reasoning: ReasoningResult
    ) -> ReviewDecision:
        self.review_calls.append((query, bundle, reasoning))
        return self._review

    async def score_evidence(self, query: QueryRequest, evidence: list) -> list:
        self.score_evidence_calls.append((query, evidence))
        return evidence


class FakeFusionService:
    def __init__(self, bundle: EvidenceBundle | None = None):
        self._bundle = bundle or make_bundle()
        self.calls: list = []

    async def fuse(self, query: QueryRequest, agent_results: list[AgentResult]) -> EvidenceBundle:
        self.calls.append((query, agent_results))
        return self._bundle


class FakeReasoner:
    def __init__(self, result: ReasoningResult | None = None):
        self._result = result or make_reasoning_result()
        self.calls: list = []

    async def reason(self, query: QueryRequest, bundle: EvidenceBundle) -> ReasoningResult:
        self.calls.append((query, bundle))
        return self._result


def make_orchestrator(
    routing: RoutingDecision | None = None,
    review: ReviewDecision | None = None,
    agents: dict[AgentName, FakeAgent] | None = None,
    fusion: FakeFusionService | None = None,
    reasoner: FakeReasoner | None = None,
) -> tuple[ManufacturaIQOrchestrator, FakeDecisionEngine, dict[AgentName, FakeAgent], FakeFusionService, FakeReasoner]:
    engine = FakeDecisionEngine(routing, review)
    agent_map = agents or {
        AgentName.DOCUMENT: FakeAgent(make_agent_result(AgentName.DOCUMENT)),
        AgentName.MAINTENANCE: FakeAgent(make_agent_result(AgentName.MAINTENANCE)),
        AgentName.QUALITY: FakeAgent(make_agent_result(AgentName.QUALITY)),
        AgentName.PRODUCTION: FakeAgent(make_agent_result(AgentName.PRODUCTION)),
    }
    fusion_svc = fusion or FakeFusionService()
    reasoner_svc = reasoner or FakeReasoner()
    orch = ManufacturaIQOrchestrator(engine, agent_map, fusion_svc, reasoner_svc)
    return orch, engine, agent_map, fusion_svc, reasoner_svc


async def test_orchestrator_satisfies_protocol() -> None:
    assert inspect.iscoroutinefunction(ManufacturaIQOrchestrator.run)


async def test_single_agent_selection() -> None:
    routing = make_routing_decision([AgentName.DOCUMENT])
    orch, engine, agents, fusion, reasoner = make_orchestrator(routing=routing)
    result = await orch.run(make_query())
    assert len(agents[AgentName.DOCUMENT].calls) == 1
    assert len(agents[AgentName.MAINTENANCE].calls) == 0
    assert len(agents[AgentName.QUALITY].calls) == 0
    assert len(agents[AgentName.PRODUCTION].calls) == 0
    assert len(fusion.calls) == 1
    assert len(reasoner.calls) == 1
    assert len(engine.review_calls) == 1


async def test_multiple_agents_selection() -> None:
    routing = make_routing_decision([AgentName.MAINTENANCE, AgentName.QUALITY, AgentName.PRODUCTION])
    orch, engine, agents, fusion, reasoner = make_orchestrator(routing=routing)
    result = await orch.run(make_query())
    assert len(agents[AgentName.MAINTENANCE].calls) == 1
    assert len(agents[AgentName.QUALITY].calls) == 1
    assert len(agents[AgentName.PRODUCTION].calls) == 1
    assert len(agents[AgentName.DOCUMENT].calls) == 0
    assert len(fusion.calls) == 1
    assert len(reasoner.calls) == 1


async def test_all_agents_selection() -> None:
    routing = make_routing_decision([
        AgentName.DOCUMENT, AgentName.MAINTENANCE, AgentName.QUALITY, AgentName.PRODUCTION
    ])
    orch, engine, agents, fusion, reasoner = make_orchestrator(routing=routing)
    result = await orch.run(make_query())
    for agent in agents.values():
        assert len(agent.calls) == 1
    assert len(fusion.calls) == 1


async def test_concurrent_execution() -> None:
    started_events: dict[str, asyncio.Event] = {}
    release_event = asyncio.Event()

    class SlowAgent:
        def __init__(self, name: str):
            self._name = name
            self._started = asyncio.Event()
            self.calls: list = []

        async def run(self, query: QueryRequest) -> AgentResult:
            self._started.set()
            await release_event.wait()
            self.calls.append(query)
            return make_agent_result(AgentName(self._name))

    agents = {
        AgentName.DOCUMENT: SlowAgent("DOCUMENT"),
        AgentName.QUALITY: SlowAgent("QUALITY"),
    }
    routing = make_routing_decision([AgentName.DOCUMENT, AgentName.QUALITY])
    engine = FakeDecisionEngine(routing=routing)
    fusion = FakeFusionService()
    reasoner = FakeReasoner()
    orch = ManufacturaIQOrchestrator(engine, agents, fusion, reasoner)

    task = asyncio.create_task(orch.run(make_query()))
    await asyncio.sleep(0.05)
    assert agents[AgentName.DOCUMENT]._started.is_set()
    assert agents[AgentName.QUALITY]._started.is_set()
    release_event.set()
    result = await task
    assert len(fusion.calls) == 1


async def test_fan_in_waits_for_all_agents() -> None:
    release_event = asyncio.Event()
    call_order: list[str] = []

    class OrderedAgent:
        def __init__(self, name: str):
            self._name = name

        async def run(self, query: QueryRequest) -> AgentResult:
            call_order.append(self._name)
            if self._name == "DOCUMENT":
                await release_event.wait()
            return make_agent_result(AgentName(self._name))

    agents = {
        AgentName.DOCUMENT: OrderedAgent("DOCUMENT"),
        AgentName.QUALITY: OrderedAgent("QUALITY"),
    }
    routing = make_routing_decision([AgentName.DOCUMENT, AgentName.QUALITY])
    engine = FakeDecisionEngine(routing=routing)
    fusion = FakeFusionService()
    reasoner = FakeReasoner()
    orch = ManufacturaIQOrchestrator(engine, agents, fusion, reasoner)

    task = asyncio.create_task(orch.run(make_query()))
    await asyncio.sleep(0.05)
    assert len(fusion.calls) == 0
    release_event.set()
    result = await task
    assert len(fusion.calls) == 1


async def test_completion_order_does_not_affect_result() -> None:
    routing = make_routing_decision([AgentName.DOCUMENT, AgentName.QUALITY])
    orch1, _, _, _, _ = make_orchestrator(routing=routing)
    result1 = await orch1.run(make_query())
    orch2, _, _, _, _ = make_orchestrator(routing=routing)
    result2 = await orch2.run(make_query())
    assert result1["query_id"] == result2["query_id"]


async def test_clarification_terminates_early() -> None:
    routing = make_routing_decision(needs_clarification=True)
    orch, engine, agents, fusion, reasoner = make_orchestrator(routing=routing)
    result = await orch.run(make_query())
    for agent in agents.values():
        assert len(agent.calls) == 0
    assert len(fusion.calls) == 0
    assert len(reasoner.calls) == 0
    assert len(engine.review_calls) == 0
    assert result.get("routing_decision") is not None


async def test_empty_selection_runs_fusion_with_empty() -> None:
    routing = make_routing_decision([])
    orch, engine, agents, fusion, reasoner = make_orchestrator(routing=routing)
    result = await orch.run(make_query())
    for agent in agents.values():
        assert len(agent.calls) == 0
    assert len(fusion.calls) == 1
    assert len(reasoner.calls) == 1


async def test_human_review_terminates_normally() -> None:
    routing = make_routing_decision([AgentName.DOCUMENT])
    review = make_review_decision(action=ReviewAction.HUMAN_REVIEW)
    orch, engine, agents, fusion, reasoner = make_orchestrator(routing=routing, review=review)
    result = await orch.run(make_query())
    assert result["review_decision"].action == ReviewAction.HUMAN_REVIEW


async def test_pass_terminates_normally() -> None:
    routing = make_routing_decision([AgentName.DOCUMENT])
    review = make_review_decision(action=ReviewAction.PASS)
    orch, engine, agents, fusion, reasoner = make_orchestrator(routing=routing, review=review)
    result = await orch.run(make_query())
    assert result["review_decision"].action == ReviewAction.PASS


async def test_partial_agent_result_does_not_abort() -> None:
    partial_result = make_agent_result(AgentName.DOCUMENT, errors=["partial failure"])
    agents = {AgentName.DOCUMENT: FakeAgent(partial_result)}
    routing = make_routing_decision([AgentName.DOCUMENT])
    orch, engine, _, fusion, reasoner = make_orchestrator(routing=routing, agents=agents)
    result = await orch.run(make_query())
    assert len(fusion.calls) == 1


async def test_unexpected_agent_error_propagates() -> None:
    agents = {AgentName.DOCUMENT: FakeAgent(error=RuntimeError("agent bug"))}
    routing = make_routing_decision([AgentName.DOCUMENT])
    orch, _, _, _, _ = make_orchestrator(routing=routing, agents=agents)
    with pytest.raises(RuntimeError, match="agent bug"):
        await orch.run(make_query())


async def test_missing_agent_raises_configuration_error() -> None:
    routing = make_routing_decision([AgentName.DOCUMENT, AgentName.QUALITY])
    agents = {AgentName.DOCUMENT: FakeAgent(make_agent_result(AgentName.DOCUMENT))}
    orch, _, _, _, _ = make_orchestrator(routing=routing, agents=agents)
    with pytest.raises(ValueError, match="No agent implementation"):
        await orch.run(make_query())


async def test_score_evidence_never_called() -> None:
    routing = make_routing_decision([AgentName.DOCUMENT])
    orch, engine, _, _, _ = make_orchestrator(routing=routing)
    await orch.run(make_query())
    assert engine.score_evidence_calls == []


async def test_same_decision_engine_for_route_and_review() -> None:
    routing = make_routing_decision([AgentName.DOCUMENT])
    orch, engine, _, _, _ = make_orchestrator(routing=routing)
    await orch.run(make_query())
    assert len(engine.route_calls) == 1
    assert len(engine.review_calls) == 1


async def test_graph_compiled_once() -> None:
    routing = make_routing_decision([AgentName.DOCUMENT])
    orch, _, _, _, _ = make_orchestrator(routing=routing)
    graph1 = orch._graph
    await orch.run(make_query())
    assert orch._graph is graph1


def test_static_architecture_boundary() -> None:
    from pathlib import Path
    source = (Path(__file__).resolve().parents[2] / "app" / "orchestration" / "workflow.py").read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden in (
        "typesafe_sdk",
        "google.genai",
        "app.repositories",
        "app.db",
        "app.rag",
        "documentretriever",
        "qdrant",
        "sqlite3",
        "aiosqlite",
        "openai",
        "groq",
        "requests",
        "httpx",
    ):
        assert forbidden not in lowered, f"forbidden reference: {forbidden}"


def test_no_direct_sql() -> None:
    from pathlib import Path
    source = (Path(__file__).resolve().parents[2] / "app" / "orchestration" / "workflow.py").read_text(encoding="utf-8")
    for keyword in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert keyword not in source
