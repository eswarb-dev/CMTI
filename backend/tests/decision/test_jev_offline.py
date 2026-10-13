from __future__ import annotations

from app.contracts.enums import EvidenceSourceType, ProviderStatus, ReviewAction, SourceKind
from app.contracts.evidence import Evidence, EvidenceProvenance
from app.contracts.fusion import EvidenceBundle
from app.contracts.query import QueryRequest
from app.contracts.reasoning import EvidenceCitation, ReasoningResult
from app.core.config import Settings
from app.decision.jev import JevDecisionEngine


class CountingTypeSafeClient:
    def __init__(self) -> None:
        self.calls = 0

    async def system_one(self, **_kwargs):
        self.calls += 1
        raise AssertionError("offline Jev path must not call provider")


def _settings_without_typesafe_key() -> Settings:
    return Settings(_env_file=None, typesafe_api_key=None, jev_enabled=True, jev_review_enabled=True)


def _query() -> QueryRequest:
    return QueryRequest(query_id="Q-JEV-OFFLINE", query="Compare Haas Safe Run with SINUMERIK collision avoidance.")


def _evidence() -> Evidence:
    return Evidence(
        evidence_id="EV-JEV-1",
        source_type=EvidenceSourceType.MANUAL,
        provenance=EvidenceProvenance(
            source_kind=SourceKind.DOCUMENT,
            source_dataset="manufacturaiq_document_corpus",
            source_id="doc-1",
            document_id="doc-1",
            chunk_id="chunk-1",
        ),
        title="Evidence",
        content="Evidence content.",
    )


async def test_no_key_routing_uses_fallback_without_provider_call() -> None:
    client = CountingTypeSafeClient()
    engine = JevDecisionEngine(client, settings=_settings_without_typesafe_key())

    decision = await engine.route(_query())

    assert client.calls == 0
    assert decision.provider_status == ProviderStatus.FALLBACK
    assert decision.decision_metadata["fallback_used"] is True
    assert decision.decision_metadata["latency_ms"] < 50


async def test_no_key_review_returns_human_review_without_provider_call() -> None:
    client = CountingTypeSafeClient()
    engine = JevDecisionEngine(client, settings=_settings_without_typesafe_key())
    query = _query()
    evidence = _evidence()
    bundle = EvidenceBundle(query_id=query.query_id, evidence=[evidence])
    reasoning = ReasoningResult(
        query_id=query.query_id,
        observations=["Observation."],
        possible_causes=[],
        recommended_checks=[],
        missing_information=[],
        citations=[EvidenceCitation(evidence_id=evidence.evidence_id)],
        raw_answer="Answer.",
        provider_status=ProviderStatus.SUCCESS,
    )

    decision = await engine.review(query, bundle, reasoning)

    assert client.calls == 0
    assert decision.action == ReviewAction.HUMAN_REVIEW
    assert decision.provider_status == ProviderStatus.FALLBACK
    assert decision.metadata["fallback_reason"] == "jev_disabled_or_no_key"
    assert decision.metadata["latency_ms"] < 50
