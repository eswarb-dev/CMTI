from __future__ import annotations

from app.rag.chunking import ChunkingConfig, HeuristicTokenCounter, build_document_chunks
from app.rag.models import DocumentNode, SectionNode


def _document(document_id: str = "USR-ABCDEF123456") -> DocumentNode:
    return DocumentNode(
        document_id=document_id,
        filename="manual.pdf",
        relative_path="",
        document_type="UPLOADED_PDF",
        title="Manual",
        sha256="s" * 64,
        page_count=2,
    )


def _sections(document_id: str = "USR-ABCDEF123456") -> list[SectionNode]:
    return [
        SectionNode(document_id=document_id, section_ordinal=index,
                    page_start=number, page_end=number,
                    text=f"Page {number} spindle lubrication procedure. " * 20,
                    page_spans=[(0, 600, number)], heading_method="dynamic_page")
        for index, number in enumerate((1, 2))
    ]


def _build(document_id: str = "USR-ABCDEF123456"):
    return build_document_chunks(
        _document(document_id), _sections(document_id),
        ChunkingConfig(), HeuristicTokenCounter(),
        embedding_model="BAAI/bge-small-en-v1.5", ingestion_version="step19b1.v1",
    )


def test_deterministic_chunk_ids() -> None:
    first = _build()
    second = _build()
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]
    assert len({c.chunk_id for c in first}) == len(first)


def test_stable_text_segmentation() -> None:
    first = _build()
    again = _build()
    assert [c.text for c in first] == [c.text for c in again]
    assert all(c.text.strip() for c in first)


def test_page_provenance_preserved() -> None:
    chunks = _build()
    assert all(c.page_start >= 1 and c.page_end >= c.page_start for c in chunks)
    assert {c.page_start for c in chunks} <= {1, 2}
    assert all(c.document_id == "USR-ABCDEF123456" for c in chunks)


def test_reingestion_does_not_duplicate_chunks(service, tmp_path) -> None:
    from tests.documents.conftest import make_pdf

    path = tmp_path / "a.pdf"
    make_pdf(path, ["Stable spindle content. " * 30])
    with open(path, "rb") as handle:
        first = service.ingest_pdf(handle, original_filename="a.pdf")
    assert first.status == "READY"
    count = service.store.point_count()
    assert count == first.chunk_count
    # Duplicate upload recognized without reindexing.
    with open(path, "rb") as handle:
        second = service.ingest_pdf(handle, original_filename="a.pdf")
    assert second.duplicate is True
    assert second.document_id == first.document_id
    assert service.store.point_count() == count
    # Deterministic re-upsert of the same chunks overwrites instead of duplicating.
    record = service.get_document(first.document_id)
    assert record is not None
    from app.documents.validation import extract_pages

    chunks = service._chunk_pages(
        record, extract_pages(service.storage.original_path(record.stored_filename)))
    assert [c.chunk_id for c in chunks] == [
        c.chunk_id for c in service._chunk_pages(
            record, extract_pages(service.storage.original_path(record.stored_filename)))]
    service._cleanup_partial_vectors(first.document_id)
    assert service.store.point_count() == 0
    vectors = service.embedder.encode([c.text for c in chunks])
    service.store.upsert([c.chunk_id for c in chunks], [list(map(float, r)) for r in vectors],
                         [{**c.to_payload(), "corpus": "dynamic"} for c in chunks], batch_size=4)
    service.store.upsert([c.chunk_id for c in chunks], [list(map(float, r)) for r in vectors],
                         [{**c.to_payload(), "corpus": "dynamic"} for c in chunks], batch_size=4)
    assert service.store.point_count() == count
