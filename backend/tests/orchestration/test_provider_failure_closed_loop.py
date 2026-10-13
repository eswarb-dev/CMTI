from __future__ import annotations

import httpx

from app.contracts.enums import (
    EvidenceSourceType,
    ProviderStatus,
    ReviewAction,
    SourceKind,
)
from app.contracts.evidence import Evidence, EvidenceProvenance
from app.contracts.fusion import EvidenceBundle
from app.contracts.query import QueryRequest
from app.contracts.reasoning import EvidenceCitation, ReasoningResult
from app.core.config import Settings
from app.decision.jev import JevDecisionEngine
from app.reasoning.gemini import GeminiReasoner


def _no_key_settings(**overrides) -> Settings:
    fields: dict = {"typesafe_api_key": None, "gemini_api_key": None}
    fields.update(overrides)
    return Settings(**fields)


def _query() -> QueryRequest:
    return QueryRequest(query_id="Q-CLOSED-LOOP", query="Show the lockout tagout procedure.")


def _bundle(query_id: str) -> EvidenceBundle:
    evidence = Evidence(
        evidence_id="EV-001",
        source_type=EvidenceSourceType.MANUAL,
        provenance=EvidenceProvenance(
            source_kind=SourceKind.DOCUMENT,
            source_dataset="technical_document_corpus",
            source_id="DOC-1",
            document_id="DOC-1",
        ),
        title="Lockout example",
        content="Example lockout procedure content.",
    )
    return EvidenceBundle(
        query_id=query_id,
        evidence=[evidence],
        conflicts=[],
        missing_information=[],
        warnings=[],
    )


class _FailingGeminiClient:
    """Fake provider client raising an expected model-not-found API error."""

    def __init__(self) -> None:
        self.calls = 0

    @property
    def aio(self):
        return self

    @property
    def interactions(self):
        return self

    async def create(self, **kwargs):
        from google.genai._gaos.lib import compat_errors as gaos_errors

        self.calls += 1
        request = httpx.Request("POST", "https://example.invalid/v1/interactions")
        response = httpx.Response(404, request=request)
        raise gaos_errors.NotFoundError("Model '' not found.", response=response, body={})

    async def close(self) -> None:
        pass


async def test_provider_failure_closes_loop_to_human_review() -> None:
    query = _query()
    bundle = _bundle(query.query_id)

    reasoner = GeminiReasoner(_FailingGeminiClient(), settings=_no_key_settings())
    reasoning = await reasoner.reason(query, bundle)

    assert isinstance(reasoning, ReasoningResult)
    assert reasoning.provider_status == ProviderStatus.UNAVAILABLE
    assert reasoning.observations == []
    assert reasoning.possible_causes == []
    assert reasoning.recommended_checks == []
    assert reasoning.citations == []

    reviewer = JevDecisionEngine(None, settings=_no_key_settings())
    decision = await reviewer.review(query, bundle, reasoning)

    assert decision.action == ReviewAction.HUMAN_REVIEW
    assert decision.action != ReviewAction.PASS
    assert decision.provider_status == ProviderStatus.FALLBACK


async def test_provider_failure_review_with_grounded_success_reasoning_stays_human_review() -> None:
    query = _query()
    bundle = _bundle(query.query_id)
    reasoning = ReasoningResult(
        query_id=query.query_id,
        observations=["Example observation"],
        possible_causes=["Example possible cause"],
        recommended_checks=["Example check"],
        missing_information=[],
        citations=[EvidenceCitation(evidence_id="EV-001")],
        raw_answer="Example grounded answer.",
        provider_status=ProviderStatus.SUCCESS,
    )
    reviewer = JevDecisionEngine(None, settings=_no_key_settings())
    decision = await reviewer.review(query, bundle, reasoning)
    assert decision.action == ReviewAction.HUMAN_REVIEW
