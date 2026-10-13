from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Mapping

from app.contracts.enums import AgentName, Domain, ProviderStatus, ReviewAction, RiskLevel
from app.contracts.fusion import EvidenceBundle
from app.contracts.query import QueryRequest
from app.contracts.reasoning import ReasoningResult
from app.contracts.review import ReviewDecision
from app.contracts.routing import RoutingDecision
from app.core.config import Settings, get_settings
from app.core.exceptions import ProviderUnavailableError
from app.protocols.decision import DecisionEngine

__all__ = ["JevDecisionEngine", "build_jev_decision_engine"]

logger = logging.getLogger(__name__)

_CANONICAL_AGENT_ORDER: tuple[AgentName, ...] = (
    AgentName.DOCUMENT,
    AgentName.MAINTENANCE,
    AgentName.QUALITY,
    AgentName.PRODUCTION,
)

_ROUTE_QUESTIONS: tuple[tuple[str, AgentName, str], ...] = (
    (
        "route_document",
        AgentName.DOCUMENT,
        "Would answering this request materially benefit from technical "
        "documentation, operating manuals, safety procedures, reference "
        "documentation, or manufacturer instructions?",
    ),
    (
        "route_maintenance",
        AgentName.MAINTENANCE,
        "Does this request require machine maintenance history, alarms, "
        "telemetry, machine-condition records, maintenance actions, or "
        "maintenance-related operational evidence?",
    ),
    (
        "route_quality",
        AgentName.QUALITY,
        "Does this request require quality-inspection measurements, "
        "specification limits, pass/fail results, defect records, or "
        "quality-inspection aggregate evidence?",
    ),
    (
        "route_production",
        AgentName.PRODUCTION,
        "Does this request require production orders, production "
        "quantities, accepted/rejected output, order status, or production "
        "rejection summary evidence?",
    ),
)

_REVIEW_QUESTIONS: tuple[tuple[str, str], ...] = (
    (
        "review_grounding_failure",
        "Does the proposed reasoning contain any material observation, "
        "hypothesis, recommendation, or conclusion that is unsupported by, "
        "inconsistent with, or materially stronger than the supplied cited "
        "evidence?",
    ),
    (
        "review_causal_overreach",
        "Does the reasoning present causation or diagnostic certainty more "
        "strongly than the supplied evidence supports, including treating "
        "correlation, temporal co-occurrence, or a possible cause as a "
        "confirmed cause?",
    ),
    (
        "review_conflict_gap_failure",
        "Does the reasoning materially fail to acknowledge a supplied "
        "source-integrity conflict, provider/data gap, or missing evidence "
        "that should limit the stated conclusion?",
    ),
    (
        "review_safety_failure",
        "Does the reasoning recommend an unsafe or insufficiently bounded "
        "action, including bypassing safety controls, defeating interlocks, "
        "ignoring lockout/tagout, or autonomously changing/operating "
        "industrial equipment without appropriate verification or human "
        "control?",
    ),
)

_ISSUE_CODES: dict[str, str] = {
    "review_grounding_failure": "grounding_failure",
    "review_causal_overreach": "causal_overreach",
    "review_conflict_gap_failure": "conflict_gap_failure",
    "review_safety_failure": "safety_failure",
}

_USER_CONTEXT_ALLOWLIST: frozenset[str] = frozenset(
    {
        "document_type",
        "manufacturer",
        "machine_family",
        "model",
        "document_id",
        "language",
    }
)


def _iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _build_state(query: QueryRequest) -> dict[str, Any]:
    routing_context: dict[str, Any] = {}
    for key in _USER_CONTEXT_ALLOWLIST:
        if key in query.user_context:
            routing_context[key] = query.user_context[key]
    return {
        "query": query.query,
        "machine_id": query.machine_id,
        "product_id": query.product_id,
        "batch_id": query.batch_id,
        "time_start": _iso_or_none(query.time_start),
        "time_end": _iso_or_none(query.time_end),
        "routing_context": routing_context,
    }


def _build_review_state(
    query: QueryRequest, bundle: Any, reasoning: ReasoningResult
) -> dict[str, Any]:
    evidence_items: list[dict[str, Any]] = []
    for ev in bundle.evidence:
        p = ev.provenance
        evidence_items.append({
            "evidence_id": ev.evidence_id,
            "source_type": ev.source_type.value,
            "source_kind": p.source_kind.value,
            "source_dataset": p.source_dataset,
            "source_id": p.source_id,
            "record_id": p.record_id,
            "document_id": p.document_id,
            "chunk_id": p.chunk_id,
            "page_start": p.page_start,
            "page_end": p.page_end,
            "machine_id": ev.machine_id,
            "product_id": ev.product_id,
            "batch_id": ev.batch_id,
            "observed_at": _iso_or_none(ev.observed_at),
            "title": ev.title,
            "content": ev.content,
            "retrieval_score": ev.retrieval_score,
            "decision_score": ev.decision_score,
        })
    return {
        "query": {
            "query_id": query.query_id,
            "query_text": query.query,
            "machine_id": query.machine_id,
            "product_id": query.product_id,
            "batch_id": query.batch_id,
            "time_start": _iso_or_none(query.time_start),
            "time_end": _iso_or_none(query.time_end),
        },
        "evidence": evidence_items,
        "conflicts": [
            {
                "conflict_id": c.conflict_id,
                "evidence_ids": c.evidence_ids,
                "conflict_type": c.conflict_type,
                "description": c.description,
            }
            for c in bundle.conflicts
        ],
        "bundle_warnings": bundle.warnings,
        "reasoning": {
            "observations": reasoning.observations,
            "possible_causes": reasoning.possible_causes,
            "recommended_checks": reasoning.recommended_checks,
            "missing_information": bundle.missing_information + reasoning.missing_information,
            "citations": [
                {"evidence_id": c.evidence_id, "label": c.label}
                for c in reasoning.citations
            ],
            "raw_answer": reasoning.raw_answer,
        },
        "provider_context": {
            "reasoning_provider_status": reasoning.provider_status.value,
            "reasoning_model": reasoning.model,
        },
    }


def _fallback_agents(query: QueryRequest) -> list[AgentName]:
    agents = [AgentName.DOCUMENT]
    if query.machine_id:
        agents.append(AgentName.MAINTENANCE)
    if query.machine_id or query.product_id or query.batch_id:
        agents.append(AgentName.QUALITY)
        agents.append(AgentName.PRODUCTION)
    return agents


def _intent_for(agents: list[AgentName]) -> Domain:
    if not agents:
        return Domain.UNKNOWN
    if len(agents) > 1:
        return Domain.MULTI_DOMAIN
    mapping = {
        AgentName.DOCUMENT: Domain.DOCUMENTATION,
        AgentName.MAINTENANCE: Domain.MAINTENANCE,
        AgentName.QUALITY: Domain.QUALITY,
        AgentName.PRODUCTION: Domain.PRODUCTION,
    }
    return mapping.get(agents[0], Domain.UNKNOWN)


def _canonical_order(agents: list[AgentName]) -> list[AgentName]:
    return [a for a in _CANONICAL_AGENT_ORDER if a in set(agents)]


class JevDecisionEngine:
    """TypeSafe Jev routing engine implementing the frozen DecisionEngine protocol.

    Jev decides WHAT should run. A later orchestration layer decides HOW/WHEN.
    """

    def __init__(
        self,
        client: Any,
        *,
        settings: Settings | None = None,
    ) -> None:
        self._client = client
        self._settings = settings or get_settings()

    async def route(self, query: QueryRequest) -> RoutingDecision:
        started = time.perf_counter()
        threshold = self._settings.jev_route_threshold
        model = self._settings.jev_model
        timeout = self._settings.jev_timeout_seconds
        max_retries = self._settings.jev_max_retries

        use_provider = (
            self._settings.jev_enabled
            and self._settings.typesafe_api_key is not None
            and self._client is not None
        )

        if not use_provider:
            return self._fallback_decision(
                query, started, "jev_disabled_or_no_key"
            )

        from typesafe_sdk import Noul, RetryPolicy

        questions: dict[str, Any] = {
            name: Noul(instructions=instructions)
            for name, _, instructions in _ROUTE_QUESTIONS
        }
        retry_policy = RetryPolicy(max_retries=max_retries)

        try:
            response = await self._client.system_one(
                state=_build_state(query),
                questions=questions,
                model=model,
                retry=retry_policy,
                timeout=timeout,
            )
        except (ProviderUnavailableError, ConnectionError, TimeoutError) as exc:
            logger.warning("Jev provider error for query %s: %s", query.query_id, exc)
            return self._fallback_decision(query, started, "provider_error")

        answers = response.answers if hasattr(response, "answers") else {}
        probabilities: dict[str, float] = {}
        for name, agent, _ in _ROUTE_QUESTIONS:
            answer = answers.get(name)
            if answer is None:
                return self._fallback_decision(query, started, "malformed_response")
            raw = getattr(answer, "noul", None)
            if raw is None or not isinstance(raw, (int, float)):
                return self._fallback_decision(query, started, "malformed_response")
            probabilities[name] = float(raw)

        selected: list[AgentName] = []
        for name, agent, _ in _ROUTE_QUESTIONS:
            if probabilities[name] >= threshold:
                selected.append(agent)

        if not selected:
            return self._fallback_decision(query, started, "all_below_threshold")

        selected = _canonical_order(selected)
        latency_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
        return RoutingDecision(
            query_id=query.query_id,
            intent=_intent_for(selected),
            selected_agents=selected,
            needs_clarification=False,
            risk_level=RiskLevel.LOW,
            confidence=None,
            provider_status=ProviderStatus.SUCCESS,
            decision_metadata={
                "route_document_probability": probabilities.get("route_document"),
                "route_maintenance_probability": probabilities.get("route_maintenance"),
                "route_quality_probability": probabilities.get("route_quality"),
                "route_production_probability": probabilities.get("route_production"),
                "threshold": threshold,
                "provider_model": model,
                "fallback_used": False,
                "latency_ms": latency_ms,
            },
        )

    def _fallback_decision(
        self, query: QueryRequest, started: float, reason: str
    ) -> RoutingDecision:
        agents = _fallback_agents(query)
        agents = _canonical_order(agents)
        latency_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
        return RoutingDecision(
            query_id=query.query_id,
            intent=_intent_for(agents),
            selected_agents=agents,
            needs_clarification=False,
            risk_level=RiskLevel.LOW,
            confidence=None,
            provider_status=ProviderStatus.FALLBACK,
            decision_metadata={
                "threshold": self._settings.jev_route_threshold,
                "provider_model": self._settings.jev_model,
                "fallback_used": True,
                "fallback_reason": reason,
                "latency_ms": latency_ms,
            },
        )

    async def score_evidence(
        self, query: QueryRequest, evidence: list[Any]
    ) -> list[Any]:
        return evidence

    async def review(
        self,
        query: QueryRequest,
        bundle: EvidenceBundle,
        reasoning: ReasoningResult,
    ) -> ReviewDecision:
        started = time.perf_counter()
        threshold = self._settings.jev_review_threshold
        model = self._settings.jev_model
        timeout = self._settings.jev_timeout_seconds
        max_retries = self._settings.jev_max_retries

        if query.query_id != bundle.query_id or query.query_id != reasoning.query_id:
            return self._review_human(
                query, started, "query_id_mismatch",
                "Query ID mismatch between query, bundle, and reasoning.",
            )

        if reasoning.provider_status != ProviderStatus.SUCCESS:
            return self._review_human(
                query, started, "reasoning_unavailable",
                f"Reasoning provider status is {reasoning.provider_status.value}; reasoning not reviewable.",
            )

        has_substance = (
            reasoning.observations
            or reasoning.possible_causes
            or reasoning.recommended_checks
        )
        if not has_substance:
            return self._review_human(
                query, started, "empty_reasoning",
                "ReasoningResult contains no substantive observations, causes, checks, or answer.",
            )

        valid_ids = {ev.evidence_id for ev in bundle.evidence}
        for citation in reasoning.citations:
            if citation.evidence_id not in valid_ids:
                return self._review_human(
                    query, started, "invalid_citation",
                    f"Citation {citation.evidence_id!r} not found in evidence bundle.",
                )

        use_provider = (
            self._settings.jev_enabled
            and self._settings.jev_review_enabled
            and self._settings.typesafe_api_key is not None
            and self._client is not None
        )
        if not use_provider:
            return self._review_human(
                query, started, "jev_disabled_or_no_key",
                "Jev review is disabled or API key is missing.",
            )

        from typesafe_sdk import Noul, RetryPolicy

        questions: dict[str, Any] = {
            name: Noul(instructions=instructions)
            for name, instructions in _REVIEW_QUESTIONS
        }
        retry_policy = RetryPolicy(max_retries=max_retries)

        try:
            response = await self._client.system_one(
                state=_build_review_state(query, bundle, reasoning),
                questions=questions,
                model=model,
                retry=retry_policy,
                timeout=timeout,
            )
        except (ProviderUnavailableError, ConnectionError, TimeoutError) as exc:
            logger.warning("Jev review provider error for query %s: %s", query.query_id, exc)
            return self._review_human(query, started, "provider_error", str(exc))

        answers = response.answers if hasattr(response, "answers") else {}
        probabilities: dict[str, float] = {}
        for name, _ in _REVIEW_QUESTIONS:
            answer = answers.get(name)
            if answer is None:
                return self._review_human(query, started, "malformed_response", "Missing review answer.")
            raw = getattr(answer, "noul", None)
            if raw is None or not isinstance(raw, (int, float)):
                return self._review_human(query, started, "malformed_response", "Invalid review answer.")
            probabilities[name] = float(raw)

        triggered: list[str] = []
        for name, _ in _REVIEW_QUESTIONS:
            if probabilities[name] >= threshold:
                triggered.append(_ISSUE_CODES[name])

        latency_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
        if triggered:
            return ReviewDecision(
                query_id=query.query_id,
                action=ReviewAction.HUMAN_REVIEW,
                reasons=triggered,
                confidence=None,
                provider_status=ProviderStatus.SUCCESS,
                metadata={
                    "review_grounding_failure_probability": probabilities.get("review_grounding_failure"),
                    "review_causal_overreach_probability": probabilities.get("review_causal_overreach"),
                    "review_conflict_gap_failure_probability": probabilities.get("review_conflict_gap_failure"),
                    "review_safety_failure_probability": probabilities.get("review_safety_failure"),
                    "review_threshold": threshold,
                    "review_model": model,
                    "triggered_checks": triggered,
                    "fallback_used": False,
                    "latency_ms": latency_ms,
                },
            )

        return ReviewDecision(
            query_id=query.query_id,
            action=ReviewAction.PASS,
            reasons=[],
            confidence=None,
            provider_status=ProviderStatus.SUCCESS,
            metadata={
                "review_grounding_failure_probability": probabilities.get("review_grounding_failure"),
                "review_causal_overreach_probability": probabilities.get("review_causal_overreach"),
                "review_conflict_gap_failure_probability": probabilities.get("review_conflict_gap_failure"),
                "review_safety_failure_probability": probabilities.get("review_safety_failure"),
                "review_threshold": threshold,
                "review_model": model,
                "triggered_checks": [],
                "fallback_used": False,
                "latency_ms": latency_ms,
            },
        )

    def _review_human(
        self, query: QueryRequest, started: float, reason: str, detail: str
    ) -> ReviewDecision:
        latency_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
        return ReviewDecision(
            query_id=query.query_id,
            action=ReviewAction.HUMAN_REVIEW,
            reasons=[reason],
            confidence=None,
            provider_status=ProviderStatus.FALLBACK,
            metadata={
                "review_threshold": self._settings.jev_review_threshold,
                "review_model": self._settings.jev_model,
                "fallback_used": True,
                "fallback_reason": reason,
                "fallback_detail": detail,
                "latency_ms": latency_ms,
            },
        )

    async def aclose(self) -> None:
        close = getattr(self._client, "aclose", None)
        if close is not None:
            await close()


def build_jev_decision_engine(
    settings: Settings | None = None,
) -> JevDecisionEngine:
    """Construct a JevDecisionEngine with an AsyncTypeSafeClient."""
    from typesafe_sdk import AsyncTypeSafeClient

    resolved = settings or get_settings()
    client = None
    if resolved.typesafe_api_key:
        client = AsyncTypeSafeClient(
            api_key=resolved.typesafe_api_key,
            model=resolved.jev_model,
        )
    return JevDecisionEngine(client, settings=resolved)
