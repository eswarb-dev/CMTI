"""Fail-closed provider evaluation without keys or network."""

from __future__ import annotations

from app.core.config import Settings
from evaluation.cases import get_suite
from evaluation.metrics import provider_failure_checks
from evaluation.runner import build_orchestrator, build_query_request


def _offline_settings() -> Settings:
    return Settings(typesafe_api_key=None, gemini_api_key=None)


def test_offline_orchestrator_builds_without_clients() -> None:
    from app.decision.jev import build_jev_decision_engine
    from app.reasoning import build_gemini_reasoner

    settings = _offline_settings()
    assert build_jev_decision_engine(settings)._client is None
    assert build_gemini_reasoner(settings)._client is None


def test_no_jev_key_review_is_human_review() -> None:
    import asyncio

    from app.decision.jev import JevDecisionEngine
    from app.contracts.enums import ProviderStatus, ReviewAction
    from app.contracts.fusion import EvidenceBundle
    from app.contracts.reasoning import ReasoningResult

    case = get_suite("smoke")[0]
    request = build_query_request(case)
    bundle = EvidenceBundle(query_id=request.query_id, evidence=[], conflicts=[],
                            missing_information=[], warnings=[])
    reasoning = ReasoningResult(
        query_id=request.query_id,
        observations=[],
        possible_causes=[],
        recommended_checks=[],
        missing_information=["Gemini API key is not configured."],
        citations=[],
        raw_answer="Grounded reasoning unavailable: Gemini API key is not configured.",
        provider_status=ProviderStatus.UNAVAILABLE,
    )
    decision = asyncio.run(
        JevDecisionEngine(None, settings=_offline_settings()).review(request, bundle, reasoning)
    )
    assert decision.action == ReviewAction.HUMAN_REVIEW
    assert decision.action != ReviewAction.PASS


def test_provider_failure_checks_require_fail_closed() -> None:
    good = provider_failure_checks("UNAVAILABLE", "HUMAN_REVIEW", [], [], [], [])
    assert all(good.values())
    bad = provider_failure_checks("SUCCESS", "PASS", ["obs"], ["cause"], ["check"], ["EV-1"])
    assert not all(bad.values())


def test_offline_mode_ignores_ambient_keys(monkeypatch) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", "ambient-key-must-be-ignored")
    monkeypatch.setenv("GEMINI_API_KEY", "ambient-key-must-be-ignored")
    orchestrator, provider_info = build_orchestrator("offline")
    assert provider_info == {"typesafe_available": False, "gemini_available": False}
    assert orchestrator._decision_engine._client is None
    assert orchestrator._reasoner._client is None
