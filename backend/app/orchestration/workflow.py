"""LangGraph workflow orchestration for ManufacturaIQ."""

from __future__ import annotations

import logging
import time
from typing import Any, Mapping

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.contracts.agents import AgentResult
from app.contracts.enums import AgentName, ReviewAction
from app.contracts.fusion import EvidenceBundle
from app.contracts.query import QueryRequest
from app.contracts.reasoning import ReasoningResult
from app.contracts.review import ReviewDecision
from app.contracts.routing import RoutingDecision
from app.orchestration.state import WorkflowResult, WorkflowState
from app.protocols.agents import Agent
from app.protocols.decision import DecisionEngine
from app.protocols.fusion import EvidenceFusionService
from app.protocols.reasoning import Reasoner

__all__ = ["ManufacturaIQOrchestrator", "build_manufacturaiq_orchestrator"]

logger = logging.getLogger(__name__)

_AGENT_NODE_NAMES: dict[AgentName, str] = {
    AgentName.DOCUMENT: "document_agent",
    AgentName.MAINTENANCE: "maintenance_agent",
    AgentName.QUALITY: "quality_agent",
    AgentName.PRODUCTION: "production_agent",
}


class ManufacturaIQOrchestrator:
    """LangGraph workflow orchestrator executing the ManufacturaIQ pipeline.

    Jev owns WHAT. LangGraph owns HOW/WHEN.
    """

    def __init__(
        self,
        decision_engine: DecisionEngine,
        agents: Mapping[AgentName, Agent],
        fusion_service: EvidenceFusionService,
        reasoner: Reasoner,
    ) -> None:
        self._decision_engine = decision_engine
        self._agents = dict(agents)
        self._fusion_service = fusion_service
        self._reasoner = reasoner
        self._graph = self._build_graph()

    def _build_graph(self) -> Any:
        builder: Any = StateGraph(WorkflowState)

        builder.add_node("route", self._route_node)
        builder.add_node("fusion", self._fusion_node)
        builder.add_node("reason", self._reason_node)
        builder.add_node("review", self._review_node)

        for agent_name, node_name in _AGENT_NODE_NAMES.items():
            builder.add_node(node_name, self._make_agent_node(agent_name))

        builder.add_edge(START, "route")
        builder.add_conditional_edges("route", self._dispatch_after_route)
        for node_name in _AGENT_NODE_NAMES.values():
            builder.add_edge(node_name, "fusion")

        builder.add_edge("fusion", "reason")
        builder.add_edge("reason", "review")
        builder.add_edge("review", END)

        return builder.compile()

    async def _route_node(self, state: WorkflowState) -> dict[str, Any]:
        query = state["query"]
        started = time.perf_counter()
        self._log_stage(query.query_id, "routing", "START")
        try:
            decision = await self._decision_engine.route(query)
            duration = self._elapsed_ms(started)
            self._log_stage(query.query_id, "routing", "END", duration)
            return {"routing_decision": decision, "perf_timings": {"routing_ms": duration, "route_ms": duration}}
        except Exception:
            self._log_stage(query.query_id, "routing", "ERROR", self._elapsed_ms(started))
            raise

    def _dispatch_after_route(self, state: WorkflowState) -> list[Send] | str:
        decision = state.get("routing_decision")
        if decision is None or decision.needs_clarification:
            return END
        if not decision.selected_agents:
            return "fusion"
        query = state["query"]
        sends: list[Send] = []
        for agent_name in decision.selected_agents:
            node_name = _AGENT_NODE_NAMES.get(agent_name)
            if node_name is None:
                raise ValueError(f"No agent node for {agent_name.value}")
            sends.append(Send(node_name, {"query": query}))
        return sends

    def _make_agent_node(self, agent_name: AgentName):
        async def agent_node(state: WorkflowState) -> dict[str, Any]:
            query = state["query"]
            agent = self._agents.get(agent_name)
            if agent is None:
                raise ValueError(f"No agent implementation for {agent_name.value}")
            started = time.perf_counter()
            stage = f"{agent_name.value.lower()}_agent"
            self._log_stage(query.query_id, stage, "START")
            try:
                result = await agent.run(query)
            except Exception:
                self._log_stage(query.query_id, stage, "ERROR", self._elapsed_ms(started))
                raise
            duration = self._elapsed_ms(started)
            self._log_stage(query.query_id, stage, "END", duration)
            timings = {
                f"agent_{agent_name.value.lower()}_ms": duration,
                f"{agent_name.value.lower()}_agent_ms": duration,
            }
            if agent_name is AgentName.DOCUMENT:
                timings["document_retrieval_ms"] = result.latency_ms
            return {"agent_results_by_name": {agent_name.value: result}, "perf_timings": timings}

        return agent_node

    async def _fusion_node(self, state: WorkflowState) -> dict[str, Any]:
        query = state["query"]
        results = self._collect_agent_results(state)
        started = time.perf_counter()
        self._log_stage(query.query_id, "fusion", "START")
        try:
            bundle = await self._fusion_service.fuse(query, results)
            duration = self._elapsed_ms(started)
            self._log_stage(query.query_id, "fusion", "END", duration)
            return {"evidence_bundle": bundle, "perf_timings": {"fusion_ms": duration}}
        except Exception:
            self._log_stage(query.query_id, "fusion", "ERROR", self._elapsed_ms(started))
            raise

    async def _reason_node(self, state: WorkflowState) -> dict[str, Any]:
        query = state["query"]
        bundle = state["evidence_bundle"]
        started = time.perf_counter()
        self._log_stage(query.query_id, "reasoning", "START")
        try:
            reasoning = await self._reasoner.reason(query, bundle)
            duration = self._elapsed_ms(started)
            self._log_stage(query.query_id, "reasoning", "END", duration)
            return {"reasoning_result": reasoning, "perf_timings": {"reasoning_ms": duration}}
        except Exception:
            self._log_stage(query.query_id, "reasoning", "ERROR", self._elapsed_ms(started))
            raise

    async def _review_node(self, state: WorkflowState) -> dict[str, Any]:
        query = state["query"]
        bundle = state["evidence_bundle"]
        reasoning = state["reasoning_result"]
        started = time.perf_counter()
        self._log_stage(query.query_id, "review", "START")
        try:
            decision = await self._decision_engine.review(query, bundle, reasoning)
            duration = self._elapsed_ms(started)
            self._log_stage(query.query_id, "review", "END", duration)
            return {"review_decision": decision, "perf_timings": {"review_ms": duration}}
        except Exception:
            self._log_stage(query.query_id, "review", "ERROR", self._elapsed_ms(started))
            raise

    @staticmethod
    def _collect_agent_results(state: WorkflowState) -> list[AgentResult]:
        results_by_name = state.get("agent_results_by_name", {})
        canonical = [
            AgentName.DOCUMENT,
            AgentName.MAINTENANCE,
            AgentName.QUALITY,
            AgentName.PRODUCTION,
        ]
        ordered: list[AgentResult] = []
        for name in canonical:
            result = results_by_name.get(name.value)
            if result is not None:
                ordered.append(result)
        for key, result in results_by_name.items():
            if key not in {n.value for n in canonical}:
                ordered.append(result)
        return ordered

    async def run(self, query: QueryRequest) -> WorkflowResult:
        started = time.perf_counter()
        initial_state: WorkflowState = {
            "query": query,
            "agent_results_by_name": {},
        }
        final_state = await self._graph.ainvoke(initial_state)

        result: WorkflowResult = {"query_id": query.query_id}

        routing = final_state.get("routing_decision")
        if routing is not None:
            result["routing_decision"] = routing

        agent_results = self._collect_agent_results(final_state)
        result["agent_results"] = agent_results

        bundle = final_state.get("evidence_bundle")
        if bundle is not None:
            result["evidence_bundle"] = bundle

        reasoning = final_state.get("reasoning_result")
        if reasoning is not None:
            result["reasoning_result"] = reasoning

        review = final_state.get("review_decision")
        if review is not None:
            result["review_decision"] = review
        timings = dict(final_state.get("perf_timings") or {})
        agent_ms = sum(value for key, value in timings.items() if key.startswith("agent_"))
        if agent_ms:
            timings["agents_ms"] = round(agent_ms, 3)
        timings["total_ms"] = self._elapsed_ms(started)
        result["perf_timings"] = timings

        return result

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return round(max(0.0, (time.perf_counter() - started) * 1000.0), 3)

    @staticmethod
    def _log_stage(query_id: str, stage: str, event: str, duration_ms: float | None = None) -> None:
        if duration_ms is None:
            logger.warning("[query_stage] query=%s %s %s", query_id, stage, event)
            return
        logger.warning(
            "[query_stage] query=%s %s %s duration_ms=%s",
            query_id,
            stage,
            event,
            duration_ms,
        )


def build_manufacturaiq_orchestrator(
    decision_engine: DecisionEngine | None = None,
    agents: Mapping[AgentName, Agent] | None = None,
    fusion_service: EvidenceFusionService | None = None,
    reasoner: Reasoner | None = None,
    document_resources: Any | None = None,
    embedding_model: Any | None = None,
) -> ManufacturaIQOrchestrator:
    """Construct a ManufacturaIQOrchestrator with all dependencies."""
    if decision_engine is None:
        from app.decision.jev import build_jev_decision_engine
        decision_engine = build_jev_decision_engine()

    if agents is None:
        from app.agents import (
            build_document_agent,
            build_maintenance_agent,
            build_production_agent,
            build_quality_agent,
        )
        from app.core.config import get_settings as _get_settings

        _settings = _get_settings()
        if _settings.document_upload_enabled:
            if document_resources is not None:
                retriever = document_resources.build_composite_retriever()
            else:
                from app.documents.retrieval import build_composite_retriever

                retriever = build_composite_retriever(settings=_settings, embedder=embedding_model)
            document_agent = build_document_agent(_settings, retriever=retriever)
        else:
            if embedding_model is not None:
                document_agent = build_document_agent(
                    _settings,
                    embedder=embedding_model,
                )
            else:
                document_agent = build_document_agent()
        agents = {
            AgentName.DOCUMENT: document_agent,
            AgentName.MAINTENANCE: build_maintenance_agent(),
            AgentName.QUALITY: build_quality_agent(),
            AgentName.PRODUCTION: build_production_agent(),
        }

    if fusion_service is None:
        from app.fusion import build_evidence_fusion_service
        fusion_service = build_evidence_fusion_service()

    if reasoner is None:
        from app.reasoning import build_gemini_reasoner
        reasoner = build_gemini_reasoner()

    return ManufacturaIQOrchestrator(decision_engine, agents, fusion_service, reasoner)
