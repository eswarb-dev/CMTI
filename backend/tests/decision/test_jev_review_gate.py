from __future__ import annotations

import inspect
import typing
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from app.contracts.enums import AgentName, EvidenceSourceType, ProviderStatus, ReviewAction, SourceKind
from app.contracts.evidence import Evidence, EvidenceProvenance
from app.contracts.fusion import EvidenceBundle, EvidenceConflict
from app.contracts.query import QueryRequest
from app.contracts.reasoning import EvidenceCitation, ReasoningResult
from app.contracts.review import ReviewDecision
from app.core.config import Settings
from app.core.exceptions import ProviderUnavailableError
from app.decision.jev import JevDecisionEngine, build_jev_decision_engine
from app.protocols.decision import DecisionEngine


def make_query(**overrides) -> QueryRequest:
    fields: dict = {"query_id": "Q-REVIEW-1", "query": "analyze production"}
    fields.update(overrides)
    return QueryRequest(**fields)


def make_evidence(evidence_id: str = "EV-001", **kwargs) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        source_type=kwargs.get("source_type", EvidenceSourceType.PRODUCTION),
        provenance=EvidenceProvenance(
            source_kind=kwargs.get("source_kind", SourceKind.DEMO_FACTORY),
            source_dataset="manufacturaiq_demo_factory",
            source_id=kwargs.get("source_id", "PO-001"),
            record_id=kwargs.get("record_id", "PO-001"),
        ),
        title="Test Evidence",
        content="Test content",
    )


def make_bundle(evidence: list[Evidence] | None = None, **kwargs) -> EvidenceBundle:
    return EvidenceBundle(
        query_id=kwargs.get("query_id", "Q-REVIEW-1"),
        evidence=evidence or [],
        conflicts=kwargs.get("conflicts", []),
        missing_information=kwargs.get("missing_information", []),
        warnings=kwargs.get("warnings", []),
    )


def make_reasoning(
    query_id: str = "Q-REVIEW-1",
    observations: list[str] | None = None,
    possible_causes: list[str] | None = None,
    recommended_checks: list[str] | None = None,
    citations: list[EvidenceCitation] | None = None,
    provider_status: ProviderStatus = ProviderStatus.SUCCESS,
    **kwargs,
) -> ReasoningResult:
    return ReasoningResult(
        query_id=query_id,
        observations=observations or ["Production rejects increased"],
        possible_causes=possible_causes or ["Machine condition may contribute"],
        recommended_checks=recommended_checks or ["Verify machine condition"],
        missing_information=kwargs.get("missing_information", []),
        citations=citations or [EvidenceCitation(evidence_id="EV-001")],
        raw_answer=kwargs.get("raw_answer", "Based on evidence, production rejects increased."),
        provider_status=provider_status,
        model=kwargs.get("model", "gemini-3.8-flash"),
    )


def make_settings(**overrides) -> Settings:
    fields: dict = {
        "typesafe_api_key": "test-key",
        "jev_model": "jev-latest",
        "jev_route_threshold": 0.50,
        "jev_timeout_seconds": 10.0,
        "jev_max_retries": 1,
        "jev_enabled": True,
        "jev_review_threshold": 0.50,
        "jev_review_enabled": True,
    }
    fields.update(overrides)
    return Settings(**fields)


def make_review_response(answers: dict[str, float]):
    response = MagicMock()
    response.answers = {}
    for name, val in answers.items():
        answer = MagicMock()
        answer.noul = val
        response.answers[name] = answer
    return response


_ALL_LOW = {
    "review_grounding_failure": 0.1,
    "review_causal_overreach": 0.1,
    "review_conflict_gap_failure": 0.1,
    "review_safety_failure": 0.1,
}


class FakeJevClient:
    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error
        self.calls: list = []

    async def system_one(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response

    async def aclose(self):
        pass


def make_engine(response=None, error=None, **settings_kwargs) -> tuple[JevDecisionEngine, FakeJevClient]:
    client = FakeJevClient(response, error)
    settings = make_settings(**settings_kwargs)
    engine = JevDecisionEngine(client, settings=settings)
    return engine, client


def test_review_satisfies_frozen_decision_engine_signature() -> None:
    assert inspect.iscoroutinefunction(JevDecisionEngine.review)
    hints = typing.get_type_hints(JevDecisionEngine.review)
    assert hints["query"] is QueryRequest
    assert hints["bundle"] is EvidenceBundle
    assert hints["reasoning"] is ReasoningResult
    assert hints["return"] is ReviewDecision
    agent_hints = typing.get_type_hints(DecisionEngine.review)
    assert agent_hints["query"] is hints["query"]
    assert agent_hints["bundle"] is hints["bundle"]
    assert agent_hints["reasoning"] is hints["reasoning"]
    assert agent_hints["return"] is hints["return"]


async def test_review_returns_frozen_review_decision() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    engine, _ = make_engine(response=make_review_response(_ALL_LOW))
    result = await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert isinstance(result, ReviewDecision)


async def test_query_id_mismatch_prevents_provider_call() -> None:
    ev = make_evidence()
    reasoning = make_reasoning(query_id="Q-DIFFERENT")
    engine, client = make_engine(response=make_review_response(_ALL_LOW))
    result = await engine.review(make_query(query_id="Q-ORIGINAL"), make_bundle([ev]), reasoning)
    assert result.action == ReviewAction.HUMAN_REVIEW
    assert client.calls == []


async def test_reasoning_unavailable_returns_human_review() -> None:
    ev = make_evidence()
    reasoning = make_reasoning(provider_status=ProviderStatus.UNAVAILABLE)
    engine, client = make_engine(response=make_review_response(_ALL_LOW))
    result = await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert result.action == ReviewAction.HUMAN_REVIEW
    assert "reasoning_unavailable" in result.reasons
    assert client.calls == []


async def test_empty_reasoning_returns_human_review() -> None:
    ev = make_evidence()
    reasoning = ReasoningResult(
        query_id="Q-REVIEW-1",
        observations=[],
        possible_causes=[],
        recommended_checks=[],
        citations=[],
        raw_answer="Grounded reasoning unavailable: no substantive content.",
        provider_status=ProviderStatus.SUCCESS,
    )
    engine, client = make_engine(response=make_review_response(_ALL_LOW))
    result = await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert result.action == ReviewAction.HUMAN_REVIEW
    assert "empty_reasoning" in result.reasons
    assert client.calls == []


async def test_invalid_citation_returns_human_review() -> None:
    ev = make_evidence()
    reasoning = make_reasoning(citations=[EvidenceCitation(evidence_id="EV-NONEXISTENT")])
    engine, client = make_engine(response=make_review_response(_ALL_LOW))
    result = await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert result.action == ReviewAction.HUMAN_REVIEW
    assert "invalid_citation" in result.reasons
    assert client.calls == []


async def test_exactly_four_review_questions_sent() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    engine, client = make_engine(response=make_review_response(_ALL_LOW))
    await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert len(client.calls) == 1
    questions = client.calls[0]["questions"]
    assert len(questions) == 4


async def test_review_question_names_stable() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    engine, client = make_engine(response=make_review_response(_ALL_LOW))
    await engine.review(make_query(), make_bundle([ev]), reasoning)
    questions = client.calls[0]["questions"]
    names = set(questions.keys())
    assert names == {
        "review_grounding_failure",
        "review_causal_overreach",
        "review_conflict_gap_failure",
        "review_safety_failure",
    }


async def test_grounding_question_semantics_present() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    engine, client = make_engine(response=make_review_response(_ALL_LOW))
    await engine.review(make_query(), make_bundle([ev]), reasoning)
    state = client.calls[0]["state"]
    assert "evidence" in state
    assert "reasoning" in state


async def test_query_included_in_provider_state() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    engine, client = make_engine(response=make_review_response(_ALL_LOW))
    await engine.review(make_query(query="analyze CNC-05"), make_bundle([ev]), reasoning)
    state = client.calls[0]["state"]
    assert "analyze CNC-05" in str(state)


async def test_evidence_included_in_provider_state() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    engine, client = make_engine(response=make_review_response(_ALL_LOW))
    await engine.review(make_query(), make_bundle([ev]), reasoning)
    state = client.calls[0]["state"]
    assert "EV-001" in str(state)


async def test_conflicts_included() -> None:
    ev = make_evidence()
    conflict = EvidenceConflict(
        conflict_id="CONFLICT-001",
        evidence_ids=["EV-001"],
        conflict_type="factual_payload_mismatch",
        description="Test",
        severity="MEDIUM",
        resolved=False,
    )
    reasoning = make_reasoning()
    engine, client = make_engine(response=make_review_response(_ALL_LOW))
    await engine.review(make_query(), make_bundle([ev], conflicts=[conflict]), reasoning)
    state = client.calls[0]["state"]
    assert "CONFLICT-001" in str(state)


async def test_bundle_warnings_included() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    engine, client = make_engine(response=make_review_response(_ALL_LOW))
    await engine.review(make_query(), make_bundle([ev], warnings=["Partial failure"]), reasoning)
    state = client.calls[0]["state"]
    assert "Partial failure" in str(state)


async def test_reasoning_observations_included() -> None:
    ev = make_evidence()
    reasoning = make_reasoning(observations=["Custom observation"])
    engine, client = make_engine(response=make_review_response(_ALL_LOW))
    await engine.review(make_query(), make_bundle([ev]), reasoning)
    state = client.calls[0]["state"]
    assert "Custom observation" in str(state)


async def test_possible_causes_included() -> None:
    ev = make_evidence()
    reasoning = make_reasoning(possible_causes=["Custom cause"])
    engine, client = make_engine(response=make_review_response(_ALL_LOW))
    await engine.review(make_query(), make_bundle([ev]), reasoning)
    state = client.calls[0]["state"]
    assert "Custom cause" in str(state)


async def test_recommended_checks_included() -> None:
    ev = make_evidence()
    reasoning = make_reasoning(recommended_checks=["Custom check"])
    engine, client = make_engine(response=make_review_response(_ALL_LOW))
    await engine.review(make_query(), make_bundle([ev]), reasoning)
    state = client.calls[0]["state"]
    assert "Custom check" in str(state)


async def test_missing_information_included() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    engine, client = make_engine(response=make_review_response(_ALL_LOW))
    await engine.review(make_query(), make_bundle([ev], missing_information=["Need more data"]), reasoning)
    state = client.calls[0]["state"]
    assert "Need more data" in str(state)


async def test_citations_included() -> None:
    ev = make_evidence()
    reasoning = make_reasoning(citations=[EvidenceCitation(evidence_id="EV-001", label="Production order")])
    engine, client = make_engine(response=make_review_response(_ALL_LOW))
    await engine.review(make_query(), make_bundle([ev]), reasoning)
    state = client.calls[0]["state"]
    assert "EV-001" in str(state)


async def test_raw_answer_included() -> None:
    ev = make_evidence()
    reasoning = make_reasoning(raw_answer="Custom raw answer text")
    engine, client = make_engine(response=make_review_response(_ALL_LOW))
    await engine.review(make_query(), make_bundle([ev]), reasoning)
    state = client.calls[0]["state"]
    assert "Custom raw answer text" in str(state)


async def test_arbitrary_user_context_excluded() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    engine, client = make_engine(response=make_review_response(_ALL_LOW))
    await engine.review(make_query(user_context={"secret": "value"}), make_bundle([ev]), reasoning)
    state = client.calls[0]["state"]
    assert "secret" not in str(state)


async def test_api_keys_never_serialized() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    engine, client = make_engine(response=make_review_response(_ALL_LOW))
    await engine.review(make_query(), make_bundle([ev]), reasoning)
    state = client.calls[0]["state"]
    assert "test-key" not in str(state)
    assert "api_key" not in str(state).lower()


async def test_issue_below_threshold_does_not_trigger() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    engine, _ = make_engine(response=make_review_response(_ALL_LOW))
    result = await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert result.action == ReviewAction.PASS


async def test_issue_equal_threshold_triggers() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    answers = {**_ALL_LOW, "review_grounding_failure": 0.50}
    engine, _ = make_engine(response=make_review_response(answers))
    result = await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert result.action == ReviewAction.HUMAN_REVIEW
    assert "grounding_failure" in result.reasons


async def test_issue_above_threshold_triggers() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    answers = {**_ALL_LOW, "review_safety_failure": 0.9}
    engine, _ = make_engine(response=make_review_response(answers))
    result = await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert result.action == ReviewAction.HUMAN_REVIEW
    assert "safety_failure" in result.reasons


async def test_one_grounding_issue_returns_human_review() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    answers = {**_ALL_LOW, "review_grounding_failure": 0.8}
    engine, _ = make_engine(response=make_review_response(answers))
    result = await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert result.action == ReviewAction.HUMAN_REVIEW


async def test_one_causal_issue_returns_human_review() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    answers = {**_ALL_LOW, "review_causal_overreach": 0.8}
    engine, _ = make_engine(response=make_review_response(answers))
    result = await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert result.action == ReviewAction.HUMAN_REVIEW


async def test_one_conflict_gap_issue_returns_human_review() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    answers = {**_ALL_LOW, "review_conflict_gap_failure": 0.8}
    engine, _ = make_engine(response=make_review_response(answers))
    result = await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert result.action == ReviewAction.HUMAN_REVIEW


async def test_one_safety_issue_returns_human_review() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    answers = {**_ALL_LOW, "review_safety_failure": 0.8}
    engine, _ = make_engine(response=make_review_response(answers))
    result = await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert result.action == ReviewAction.HUMAN_REVIEW


async def test_multiple_issues_preserved_deterministically() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    answers = {
        "review_grounding_failure": 0.8,
        "review_causal_overreach": 0.7,
        "review_conflict_gap_failure": 0.1,
        "review_safety_failure": 0.1,
    }
    engine, _ = make_engine(response=make_review_response(answers))
    result = await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert result.action == ReviewAction.HUMAN_REVIEW
    assert "grounding_failure" in result.reasons
    assert "causal_overreach" in result.reasons


async def test_all_four_low_returns_pass() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    engine, _ = make_engine(response=make_review_response(_ALL_LOW))
    result = await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert result.action == ReviewAction.PASS


async def test_possible_causes_alone_do_not_force_human_review() -> None:
    ev = make_evidence()
    reasoning = make_reasoning(possible_causes=["Machine condition may contribute"])
    engine, _ = make_engine(response=make_review_response(_ALL_LOW))
    result = await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert result.action == ReviewAction.PASS


async def test_missing_information_alone_does_not_force_human_review() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    engine, _ = make_engine(response=make_review_response(_ALL_LOW))
    result = await engine.review(make_query(), make_bundle([ev], missing_information=["Need more data"]), reasoning)
    assert result.action == ReviewAction.PASS


async def test_conflicts_alone_do_not_force_human_review() -> None:
    ev = make_evidence()
    conflict = EvidenceConflict(
        conflict_id="CONFLICT-001",
        evidence_ids=["EV-001"],
        conflict_type="factual_payload_mismatch",
        description="Test",
        severity="MEDIUM",
        resolved=False,
    )
    reasoning = make_reasoning()
    engine, _ = make_engine(response=make_review_response(_ALL_LOW))
    result = await engine.review(make_query(), make_bundle([ev], conflicts=[conflict]), reasoning)
    assert result.action == ReviewAction.PASS


async def test_correctly_conflict_aware_response_can_pass() -> None:
    ev = make_evidence()
    conflict = EvidenceConflict(
        conflict_id="CONFLICT-001",
        evidence_ids=["EV-001"],
        conflict_type="factual_payload_mismatch",
        description="Test",
        severity="MEDIUM",
        resolved=False,
    )
    reasoning = make_reasoning(observations=["Conflict acknowledged in evidence"])
    engine, _ = make_engine(response=make_review_response(_ALL_LOW))
    result = await engine.review(make_query(), make_bundle([ev], conflicts=[conflict]), reasoning)
    assert result.action == ReviewAction.PASS


async def test_safe_verification_check_can_pass() -> None:
    ev = make_evidence()
    reasoning = make_reasoning(recommended_checks=["Inspect machine condition", "Review manual"])
    engine, _ = make_engine(response=make_review_response(_ALL_LOW))
    result = await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert result.action == ReviewAction.PASS


async def test_unsafe_bypass_recommendation_triggers_review() -> None:
    ev = make_evidence()
    reasoning = make_reasoning(recommended_checks=["Bypass safety interlock"])
    answers = {**_ALL_LOW, "review_safety_failure": 0.9}
    engine, _ = make_engine(response=make_review_response(answers))
    result = await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert result.action == ReviewAction.HUMAN_REVIEW


async def test_missing_api_key_returns_human_review() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    engine, client = make_engine(response=make_review_response(_ALL_LOW), typesafe_api_key=None)
    result = await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert result.action == ReviewAction.HUMAN_REVIEW
    assert client.calls == []


async def test_jev_enabled_false_returns_human_review() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    engine, client = make_engine(response=make_review_response(_ALL_LOW), jev_enabled=False)
    result = await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert result.action == ReviewAction.HUMAN_REVIEW
    assert client.calls == []


async def test_jev_review_enabled_false_returns_human_review() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    engine, client = make_engine(response=make_review_response(_ALL_LOW), jev_review_enabled=False)
    result = await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert result.action == ReviewAction.HUMAN_REVIEW
    assert client.calls == []


async def test_timeout_returns_human_review() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    engine, _ = make_engine(error=TimeoutError("timeout"))
    result = await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert result.action == ReviewAction.HUMAN_REVIEW


async def test_connection_failure_returns_human_review() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    engine, _ = make_engine(error=ConnectionError("connection failed"))
    result = await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert result.action == ReviewAction.HUMAN_REVIEW


async def test_api_error_returns_human_review() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    engine, _ = make_engine(error=ProviderUnavailableError("api error"))
    result = await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert result.action == ReviewAction.HUMAN_REVIEW


async def test_malformed_provider_response_returns_human_review() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    bad_response = MagicMock()
    bad_response.answers = {}
    engine, _ = make_engine(response=bad_response)
    result = await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert result.action == ReviewAction.HUMAN_REVIEW


async def test_missing_noul_answer_returns_human_review() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    partial_response = MagicMock()
    partial_response.answers = {}
    engine, _ = make_engine(response=partial_response)
    result = await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert result.action == ReviewAction.HUMAN_REVIEW


async def test_nonnumeric_answer_returns_human_review() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    bad_response = MagicMock()
    bad_response.answers = {}
    for name in ["review_grounding_failure", "review_causal_overreach", "review_conflict_gap_failure", "review_safety_failure"]:
        answer = MagicMock()
        answer.noul = "not_a_number"
        bad_response.answers[name] = answer
    engine, _ = make_engine(response=bad_response)
    result = await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert result.action == ReviewAction.HUMAN_REVIEW


async def test_provider_failure_never_becomes_pass() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    engine, _ = make_engine(error=ProviderUnavailableError("fail"))
    result = await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert result.action != ReviewAction.PASS


async def test_review_probabilities_remain_diagnostics_only() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    engine, _ = make_engine(response=make_review_response(_ALL_LOW))
    result = await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert "review_grounding_failure_probability" in result.metadata


async def test_retrieval_score_unchanged() -> None:
    ev = make_evidence()
    ev.retrieval_score = 0.85
    reasoning = make_reasoning()
    engine, _ = make_engine(response=make_review_response(_ALL_LOW))
    await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert ev.retrieval_score == 0.85


async def test_decision_score_unchanged() -> None:
    ev = make_evidence()
    ev.decision_score = None
    reasoning = make_reasoning()
    engine, _ = make_engine(response=make_review_response(_ALL_LOW))
    await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert ev.decision_score is None


async def test_bundle_not_mutated() -> None:
    ev = make_evidence()
    bundle = make_bundle([ev])
    reasoning = make_reasoning()
    engine, _ = make_engine(response=make_review_response(_ALL_LOW))
    await engine.review(make_query(), bundle, reasoning)
    assert len(bundle.evidence) == 1


async def test_reasoning_not_mutated() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    original_obs = list(reasoning.observations)
    engine, _ = make_engine(response=make_review_response(_ALL_LOW))
    await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert reasoning.observations == original_obs


async def test_evidence_not_mutated() -> None:
    ev = make_evidence()
    original_dump = ev.model_dump()
    reasoning = make_reasoning()
    engine, _ = make_engine(response=make_review_response(_ALL_LOW))
    await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert ev.model_dump() == original_dump


async def test_review_does_not_rewrite_answer() -> None:
    ev = make_evidence()
    reasoning = make_reasoning(raw_answer="Original answer")
    engine, _ = make_engine(response=make_review_response(_ALL_LOW))
    await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert reasoning.raw_answer == "Original answer"


async def test_review_does_not_execute_agents() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    engine, _ = make_engine(response=make_review_response(_ALL_LOW))
    assert not hasattr(engine, "_document_agent")
    assert not hasattr(engine, "_maintenance_agent")


async def test_review_does_not_access_repositories() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    engine, _ = make_engine(response=make_review_response(_ALL_LOW))
    assert not hasattr(engine, "_repository")


async def test_review_does_not_access_db() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    engine, _ = make_engine(response=make_review_response(_ALL_LOW))
    assert not hasattr(engine, "_db")


async def test_review_does_not_access_rag() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    engine, _ = make_engine(response=make_review_response(_ALL_LOW))
    assert not hasattr(engine, "_retriever")


async def test_review_does_not_call_gemini() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    engine, _ = make_engine(response=make_review_response(_ALL_LOW))
    assert not hasattr(engine, "_gemini_client")


async def test_review_does_not_use_langgraph() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    engine, _ = make_engine(response=make_review_response(_ALL_LOW))
    assert not hasattr(engine, "_langgraph")


async def test_review_does_not_read_hidden_ground_truth() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    engine, client = make_engine(response=make_review_response(_ALL_LOW))
    await engine.review(make_query(), make_bundle([ev]), reasoning)
    state = client.calls[0]["state"]
    assert "hidden_simulated_cause" not in str(state)
    assert "demo_cases" not in str(state)


async def test_unexpected_programming_error_propagates() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    engine, _ = make_engine(error=ValueError("programming bug"))
    with pytest.raises(ValueError, match="programming bug"):
        await engine.review(make_query(), make_bundle([ev]), reasoning)


async def test_route_regression_unchanged() -> None:
    from typesafe_sdk import Noul
    ev = make_evidence()
    reasoning = make_reasoning()
    engine, client = make_engine(response=make_review_response(_ALL_LOW))
    route_result = await engine.route(make_query(machine_id="CNC-05"))
    assert route_result.query_id == "Q-REVIEW-1"
    assert len(route_result.selected_agents) >= 1


async def test_route_question_names_unchanged() -> None:
    engine, client = make_engine(response=make_review_response(_ALL_LOW))
    await engine.route(make_query(machine_id="CNC-05"))
    route_questions = client.calls[0]["questions"]
    assert set(route_questions.keys()) == {
        "route_document",
        "route_maintenance",
        "route_quality",
        "route_production",
    }


async def test_route_fallback_unchanged() -> None:
    engine, _ = make_engine(typesafe_api_key=None)
    result = await engine.route(make_query(machine_id="CNC-05"))
    assert result.provider_status == ProviderStatus.FALLBACK


async def test_route_canonical_ordering_unchanged() -> None:
    engine, _ = make_engine(response=make_review_response(_ALL_LOW))
    result = await engine.route(make_query(machine_id="CNC-05"))
    agents = result.selected_agents
    if len(agents) > 1:
        order = [AgentName.DOCUMENT, AgentName.MAINTENANCE, AgentName.QUALITY, AgentName.PRODUCTION]
        indices = [order.index(a) for a in agents if a in order]
        assert indices == sorted(indices)


async def test_score_evidence_remains_placeholder() -> None:
    ev = make_evidence()
    engine, _ = make_engine()
    result = await engine.score_evidence(make_query(), [ev])
    assert result == [ev]


async def test_same_valid_inputs_same_provider_values_same_result() -> None:
    ev = make_evidence()
    reasoning = make_reasoning()
    engine, _ = make_engine(response=make_review_response(_ALL_LOW))
    r1 = await engine.review(make_query(), make_bundle([ev]), reasoning)
    r2 = await engine.review(make_query(), make_bundle([ev]), reasoning)
    assert r1.action == r2.action
    assert r1.reasons == r2.reasons
