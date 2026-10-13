from __future__ import annotations

from fastapi.testclient import TestClient

from app.contracts.enums import EvidenceSourceType, ProviderStatus, ReviewAction, SourceKind
from app.contracts.evidence import Evidence, EvidenceProvenance
from app.contracts.fusion import EvidenceBundle
from app.contracts.query import QueryRequest
from app.contracts.reasoning import EvidenceCitation, ReasoningResult
from app.core.config import Settings
from app.main import create_app


def no_key_settings(**overrides) -> Settings:
    fields: dict = {"typesafe_api_key": None, "gemini_api_key": None}
    fields.update(overrides)
    return Settings(**fields)


def make_query(**overrides) -> QueryRequest:
    fields: dict = {"query_id": "Q-NOKEY-1", "query": "show production report"}
    fields.update(overrides)
    return QueryRequest(**fields)


def make_evidence(evidence_id: str = "EV-001") -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        source_type=EvidenceSourceType.PRODUCTION,
        provenance=EvidenceProvenance(
            source_kind=SourceKind.DEMO_FACTORY,
            source_dataset="manufacturaiq_demo_factory",
            source_id="PO-001",
            record_id="PO-001",
        ),
        title="Test Evidence",
        content="Test content",
    )


def test_jev_builder_no_key_yields_absent_client():
    from app.decision.jev import build_jev_decision_engine

    engine = build_jev_decision_engine(no_key_settings())
    assert engine._client is None


def test_gemini_builder_no_key_yields_absent_client():
    from app.reasoning.gemini import build_gemini_reasoner

    reasoner = build_gemini_reasoner(no_key_settings())
    assert reasoner._client is None


def test_builders_single_key_absent():
    from app.decision.jev import build_jev_decision_engine
    from app.reasoning.gemini import build_gemini_reasoner

    assert build_jev_decision_engine(no_key_settings())._client is None
    assert build_gemini_reasoner(no_key_settings())._client is None


def test_builders_with_keys_use_fakes(monkeypatch):
    import typesafe_sdk

    sentinel_jev, sentinel_gemini = object(), object()
    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", lambda **kw: sentinel_jev, raising=False)
    import sys
    import types

    fake_genai = types.SimpleNamespace(Client=lambda **kw: sentinel_gemini)
    monkeypatch.setitem(sys.modules, "google", types.ModuleType("google"))
    sys.modules["google"].genai = fake_genai
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)

    from app.decision.jev import build_jev_decision_engine
    from app.reasoning.gemini import build_gemini_reasoner

    eng = build_jev_decision_engine(Settings(typesafe_api_key="k1", gemini_api_key="k2"))
    assert eng._client is sentinel_jev
    rsn = build_gemini_reasoner(Settings(typesafe_api_key="k1", gemini_api_key="k2"))
    assert rsn._client is sentinel_gemini


def test_startup_makes_zero_provider_calls(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    import app.main as main_module

    calls: list = []

    def factory():
        calls.append("orchestrator-built")
        from unittest.mock import AsyncMock

        m = AsyncMock()
        m.aclose.return_value = None
        return m

    monkeypatch.setattr(main_module, "build_manufacturaiq_orchestrator", factory)
    app = create_app(orchestrator_factory=factory)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 200
    assert calls == ["orchestrator-built"]


def test_no_fake_default_api_key():
    assert Settings.model_fields["typesafe_api_key"].default is None
    assert Settings.model_fields["gemini_api_key"].default is None


async def test_jev_route_missing_key_fallback_unchanged():
    from app.decision.jev import JevDecisionEngine

    eng = JevDecisionEngine(None, settings=no_key_settings())
    d = await eng.route(make_query())
    assert d.provider_status == ProviderStatus.FALLBACK
    assert d.decision_metadata["fallback_used"] is True


async def test_gemini_missing_key_unavailable_unchanged():
    from app.reasoning.gemini import GeminiReasoner

    q = make_query()
    bundle = EvidenceBundle(query_id=q.query_id, evidence=[make_evidence()],
                            conflicts=[], missing_information=[], warnings=[])
    out = await GeminiReasoner(None, settings=no_key_settings()).reason(q, bundle)
    assert out.provider_status == ProviderStatus.UNAVAILABLE


async def test_jev_review_missing_key_human_review_unchanged():
    from app.decision.jev import JevDecisionEngine

    q = make_query()
    bundle = EvidenceBundle(query_id=q.query_id, evidence=[make_evidence()],
                            conflicts=[], missing_information=[], warnings=[])
    reasoning = ReasoningResult(
        query_id=q.query_id,
        observations=["Production rejects increased"],
        possible_causes=["Machine condition may contribute"],
        recommended_checks=["Verify machine condition"],
        missing_information=[],
        citations=[EvidenceCitation(evidence_id="EV-001")],
        raw_answer="Based on evidence, production rejects increased.",
        provider_status=ProviderStatus.SUCCESS,
    )
    dec = await JevDecisionEngine(None, settings=no_key_settings()).review(q, bundle, reasoning)
    assert dec.action == ReviewAction.HUMAN_REVIEW
    assert dec.provider_status == ProviderStatus.FALLBACK


async def test_shutdown_with_never_constructed_clients():
    from app.decision.jev import JevDecisionEngine
    from app.reasoning.gemini import GeminiReasoner

    await JevDecisionEngine(None, settings=no_key_settings()).aclose()
    await GeminiReasoner(None, settings=no_key_settings()).aclose()


def test_full_orchestrator_builds_with_both_absent():
    from app.decision.jev import build_jev_decision_engine
    from app.orchestration import build_manufacturaiq_orchestrator
    from app.reasoning.gemini import build_gemini_reasoner

    s = no_key_settings()
    orch = build_manufacturaiq_orchestrator(
        decision_engine=build_jev_decision_engine(s),
        reasoner=build_gemini_reasoner(s),
    )
    assert orch is not None
