from __future__ import annotations

from app.contracts.query import QueryRequest
from app.documents.retrieval import (
    CompositeDocumentRetriever,
    DynamicDocumentRetriever,
    build_composite_retriever,
)
from tests.documents.conftest import make_pdf

UNIQUE_PHRASE = "zephyr torque calibrator seven"


def _ingest(service, tmp_path, phrase: str = UNIQUE_PHRASE):
    path = tmp_path / "dyn.pdf"
    make_pdf(path, [f"Maintenance note about the {phrase} for spindle service. " * 12,
                    f"Second page mentions {phrase} torque values. " * 12])
    with open(path, "rb") as handle:
        result = service.ingest_pdf(handle, original_filename="dyn.pdf")
    assert result.status == "READY"
    return result


def _query(text: str = UNIQUE_PHRASE) -> QueryRequest:
    return QueryRequest(query_id="Q-DYN-1", query=text)


def test_dynamic_retrieval_end_to_end(service, tmp_path, real_embedder) -> None:
    import asyncio

    service.embedder = real_embedder
    expected = _ingest(service, tmp_path)
    retriever = DynamicDocumentRetriever(
        path=service.store.path, collection=service.store.collection,
        embedder=real_embedder, settings=service.settings, store=service.store)
    try:
        evidence = asyncio.run(retriever.retrieve(_query(), top_k=5))
    finally:
        pass  # store owned by the service fixture
    assert evidence, "unique phrase must retrieve the dynamic document"
    first = evidence[0]
    assert first.provenance.document_id == expected.document_id
    assert first.provenance.page_start is not None and first.provenance.page_start >= 1
    assert first.provenance.chunk_id
    assert first.title
    assert UNIQUE_PHRASE in first.content
    assert first.provenance.source_dataset == "manufacturaiq_dynamic_documents"


def test_composite_calls_both_merges_dedupes_topk() -> None:
    from app.rag.scoring import RankedHit
    from app.rag.vector_store import SearchHit

    def hit(chunk_id, score, document_id="DOC-X", page=1):
        return RankedHit(
            hit=SearchHit(chunk_id=chunk_id, score=score,
                          payload={"chunk_id": chunk_id, "document_id": document_id,
                                   "page_start": page, "section_key": f"{document_id}::s",
                                   "content_hash": chunk_id, "text": "t"}),
            rank=1, score=score, section_key=f"{document_id}::s")

    class FakeSource:
        def __init__(self, hits):
            self._hits = hits
            self.calls = 0

        def search_sync(self, query, top_k=5):
            self.calls += 1
            return list(self._hits)

        def to_evidence(self, ranked):
            from app.contracts.enums import EvidenceSourceType, SourceKind
            from app.contracts.evidence import Evidence, EvidenceProvenance

            return Evidence(
                evidence_id=f"EVIDENCE-{ranked.hit.chunk_id}",
                source_type=EvidenceSourceType.MANUAL,
                provenance=EvidenceProvenance(
                    source_kind=SourceKind.DOCUMENT, source_dataset="d",
                    source_id=ranked.hit.chunk_id, document_id="D",
                    chunk_id=ranked.hit.chunk_id),
                title="t", content="c")

    static = FakeSource([hit("CHUNK-A", 0.9), hit("CHUNK-B", 0.5)])
    dynamic = FakeSource([hit("CHUNK-A", 0.95), hit("CHUNK-C", 0.7)])
    composite = CompositeDocumentRetriever(static, dynamic)
    query = _query()
    ranked = composite.search_sync(query, top_k=2)
    assert static.calls == 1 and dynamic.calls == 1
    assert [r.hit.chunk_id for r in ranked] == ["CHUNK-A", "CHUNK-C"]  # dedupe, top_k
    assert [r.rank for r in ranked] == [1, 2]

    import asyncio

    before = ([(h.hit.chunk_id, h.score) for h in static._hits],
              [(h.hit.chunk_id, h.score) for h in dynamic._hits])
    evidence = asyncio.run(composite.retrieve(query, top_k=3))
    assert [e.evidence_id for e in evidence] == ["EVIDENCE-CHUNK-A", "EVIDENCE-CHUNK-C", "EVIDENCE-CHUNK-B"]
    after = ([(h.hit.chunk_id, h.score) for h in static._hits],
             [(h.hit.chunk_id, h.score) for h in dynamic._hits])
    assert before == after  # underlying results unmutated


def test_document_agent_consumes_dynamic_evidence(service, tmp_path, real_embedder) -> None:
    import asyncio

    from app.agents.document import DocumentAgent

    service.embedder = real_embedder
    expected = _ingest(service, tmp_path)
    retriever = DynamicDocumentRetriever(
        path=service.store.path, collection=service.store.collection,
        embedder=real_embedder, settings=service.settings, store=service.store)
    try:
        agent = DocumentAgent(retriever, settings=service.settings)
        result = asyncio.run(agent.run(_query()))
    finally:
        pass  # store owned by the service fixture
    assert result.evidence, "agent must return dynamic evidence without knowing it is dynamic"
    assert result.query_id == "Q-DYN-1"
    assert any(e.provenance.document_id == expected.document_id for e in result.evidence)


def test_composite_empty_dynamic_matches_static() -> None:
    from app.contracts.query import QueryRequest
    from app.rag.retrieval import DocumentRetrieverImpl

    static = DocumentRetrieverImpl()
    try:
        composite = build_composite_retriever(static_retriever=static)
        query = QueryRequest(query_id="Q-CMP", query="spindle lubrication")
        expected = static.search_sync(query, top_k=5)
        actual = composite.search_sync(query, top_k=5)
    finally:
        composite.close()
        static.close()
    assert [h.hit.chunk_id for h in actual] == [h.hit.chunk_id for h in expected]
    assert [h.score for h in actual] == [h.score for h in expected]


def test_static_collection_untouched_by_dynamic_suite(service, tmp_path) -> None:
    from app.core.config import Settings, get_settings

    settings = get_settings()
    assert settings.rag_collection_name == "manufacturaiq_documents"
    assert Settings(_env_file=None).document_dynamic_collection == "manufacturaiq_dynamic_documents"
    assert service.store.collection != settings.rag_collection_name
    assert service.store.path.resolve() != settings.vector_store_path.resolve()
