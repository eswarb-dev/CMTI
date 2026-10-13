"""Internal LangGraph workflow state for ManufacturaIQ orchestration."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from app.contracts.agents import AgentResult
from app.contracts.enums import AgentName
from app.contracts.fusion import EvidenceBundle
from app.contracts.query import QueryRequest
from app.contracts.reasoning import ReasoningResult
from app.contracts.review import ReviewDecision
from app.contracts.routing import RoutingDecision


def _merge_agent_results(
    left: dict[str, AgentResult] | None, right: dict[str, AgentResult] | None
) -> dict[str, AgentResult]:
    merged: dict[str, AgentResult] = dict(left or {})
    for key, value in (right or {}).items():
        if key in merged:
            raise ValueError(f"Duplicate agent result for {key}")
        merged[key] = value
    return merged


def _merge_perf_timings(
    left: dict[str, float] | None, right: dict[str, float] | None
) -> dict[str, float]:
    merged: dict[str, float] = dict(left or {})
    for key, value in (right or {}).items():
        merged[key] = value
    return merged


class WorkflowState(TypedDict, total=False):
    query: QueryRequest
    routing_decision: RoutingDecision
    agent_results_by_name: Annotated[dict[str, AgentResult], _merge_agent_results]
    evidence_bundle: EvidenceBundle
    reasoning_result: ReasoningResult
    review_decision: ReviewDecision
    perf_timings: Annotated[dict[str, float], _merge_perf_timings]


class WorkflowResult(TypedDict, total=False):
    query_id: str
    routing_decision: RoutingDecision
    agent_results: list[AgentResult]
    evidence_bundle: EvidenceBundle
    reasoning_result: ReasoningResult
    review_decision: ReviewDecision
    perf_timings: dict[str, float]
