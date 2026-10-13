from __future__ import annotations

from app.contracts.enums import EvidenceSourceType, SourceKind
from app.contracts.query import QueryRequest
from app.rag.models import map_document_source_type


def make_query(text: str, **kwargs) -> QueryRequest:
    defaults = dict(query_id="Q-EV", query=text, user_context={})
    defaults.update(kwargs)
    return QueryRequest(**defaults)


def test_source_type_mapping_is_deterministic_and_scoped() -> None:
    assert map_document_source_type("SAFETY") is EvidenceSourceType.SAFETY
    assert map_document_source_type("MACHINE_SAFETY") is EvidenceSourceType.SAFETY
    assert map_document_source_type("Safety Notice") is EvidenceSourceType.SAFETY
    assert map_document_source_type("SOP-14") is EvidenceSourceType.SOP
    assert map_document_source_type("OPERATOR_MANUAL") is EvidenceSourceType.MANUAL
    assert map_document_source_type("TECHNICAL_REFERENCE") is EvidenceSourceType.MANUAL
    assert map_document_source_type("manual") is EvidenceSourceType.MANUAL
    assert map_document_source_type(None) is EvidenceSourceType.MANUAL
    assert map_document_source_type("SOMETHING_ELSE") is EvidenceSourceType.MANUAL
    assert map_document_source_type("SOMETHING_ELSE") is not EvidenceSourceType.EXTERNAL_DATASET


async def test_evidence_carries_complete_document_provenance(retriever, settings) -> None:
    evidences = await retriever.retrieve(make_query("G00 rapid motion"), top_k=3)

    assert evidences
    for rank, evidence in enumerate(evidences, start=1):
        provenance = evidence.provenance

        assert evidence.evidence_id == f"EVIDENCE-{provenance.chunk_id}"
        assert provenance.source_kind is SourceKind.DOCUMENT
        assert provenance.source_dataset == "manufacturaiq_document_corpus"
        assert provenance.source_id == provenance.chunk_id
        assert provenance.chunk_id and provenance.chunk_id.startswith("CHUNK-")
        assert provenance.document_id and provenance.document_id.startswith("DOC-")
        assert provenance.source_file and provenance.source_file.lower().endswith(".pdf")
        assert provenance.page_start is not None and provenance.page_start >= 1
        assert provenance.page_end is not None
        assert provenance.page_start <= provenance.page_end
        assert evidence.source_type in set(EvidenceSourceType)
        assert evidence.title.strip() and len(evidence.title) <= 300
        assert evidence.content.strip()
        assert evidence.retrieval_score is not None
        assert 0.0 < evidence.retrieval_score <= 1.0
        assert evidence.decision_score is None
        assert evidence.machine_id is None
        assert evidence.product_id is None
        assert evidence.batch_id is None
        assert evidence.observed_at is None


async def test_evidence_metadata_exposes_hierarchy_and_neighbour_context(retriever, settings) -> None:
    evidences = await retriever.retrieve(make_query("G00 rapid motion"), top_k=3)

    assert evidences
    ordering = [
        item.metadata["rerank_score"]
        if item.metadata.get("rerank_score") is not None
        else item.retrieval_score
        for item in evidences
    ]
    assert ordering == sorted(ordering, reverse=True)

    for rank, evidence in enumerate(evidences, start=1):
        metadata = evidence.metadata

        assert metadata["chunk_id"] == evidence.provenance.chunk_id
        assert metadata["document_id"] == evidence.provenance.document_id
        assert metadata["retrieval_rank"] == rank
        assert metadata["embedding_model"] == settings.embedding_model
        assert metadata["ingestion_version"] == "step06.v1"
        assert isinstance(metadata["heading_path"], list)
        assert metadata["page_start"] <= metadata["page_end"]
        assert metadata["token_count"] <= settings.rag_chunk_max_tokens
        assert len(metadata["content_hash"]) == 64
        assert metadata["section_key"].startswith(metadata["document_id"])
        assert metadata["previous_chunk_id"] is not None or metadata["next_chunk_id"] is not None


async def test_title_joins_document_title_with_the_section_heading(retriever) -> None:
    evidences = await retriever.retrieve(make_query("G00 rapid motion"), top_k=5)

    with_heading = [
        item
        for item in evidences
        if item.metadata.get("heading_path") and item.metadata.get("title")
    ]
    assert with_heading

    sample = with_heading[0]
    document_title = sample.metadata["title"]
    heading = sample.metadata["heading_path"][-1]
    assert sample.title.startswith(document_title)
    assert heading in sample.title
    assert len(sample.title) <= 300


async def test_retrieval_score_stays_vector_while_blend_lives_in_metadata(
    retriever, settings
) -> None:
    evidences = await retriever.retrieve(make_query("SINUMERIK tool management"), top_k=5)

    assert evidences
    assert settings.rag_lexical_weight > 0.0
    for evidence in evidences:
        metadata = evidence.metadata

        # Policy: retrieval_score is the raw vector similarity, never the blend.
        assert evidence.retrieval_score == metadata["vector_score_raw"]
        assert 0.0 < evidence.retrieval_score <= 1.0
        assert isinstance(metadata["lexical_score"], float)
        assert 0.0 <= metadata["lexical_score"] <= 1.0
        assert isinstance(metadata["rerank_score"], float)
        expected_blend = (
            (1.0 - settings.rag_lexical_weight) * metadata["vector_score_raw"]
            + settings.rag_lexical_weight * metadata["lexical_score"]
        )
        assert metadata["rerank_score"] == expected_blend
