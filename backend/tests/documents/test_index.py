from __future__ import annotations

from app.documents.ingestion import DYNAMIC_SOURCE_DATASET


def test_dynamic_collection_created(service) -> None:
    assert service.store.collection_exists() is False
    service.store.ensure_collection(384)
    assert service.store.collection_exists() is True


def test_dimension_correct(service) -> None:
    service.store.ensure_collection(service.embedder.dimension)
    info = service.store.client.get_collection(service.store.collection)
    assert int(info.config.params.vectors.size) == 384


def test_distance_compatible(service) -> None:
    from qdrant_client import models

    service.store.ensure_collection(384)
    info = service.store.client.get_collection(service.store.collection)
    assert info.config.params.vectors.distance == models.Distance.COSINE


def test_payload_provenance_correct(service, tmp_path) -> None:
    from tests.documents.conftest import make_pdf

    path = tmp_path / "a.pdf"
    make_pdf(path, ["Bearing replacement torque specification content. " * 20])
    with open(path, "rb") as handle:
        result = service.ingest_pdf(handle, original_filename="a.pdf")
    assert result.status == "READY"
    hits = service.store.client.scroll(service.store.collection, limit=10)[0]
    assert len(hits) == result.chunk_count
    payload = dict(hits[0].payload)
    assert payload["document_id"] == result.document_id
    assert payload["corpus"] == "dynamic"
    assert payload["source_dataset"] == DYNAMIC_SOURCE_DATASET
    assert payload["page_start"] >= 1
    assert payload["chunk_id"].startswith("CHUNK-USR-")


def test_vector_count_equals_chunk_count(service, tmp_path) -> None:
    from tests.documents.conftest import make_pdf

    path = tmp_path / "a.pdf"
    make_pdf(path, ["Count check content. " * 40, "Second page content here. " * 40])
    with open(path, "rb") as handle:
        result = service.ingest_pdf(handle, original_filename="a.pdf")
    assert result.status == "READY"
    assert service.store.point_count() == result.chunk_count


def test_retry_does_not_increase_count(service, tmp_path) -> None:
    from tests.documents.conftest import make_pdf

    path = tmp_path / "a.pdf"
    make_pdf(path, ["Retry content spindle. " * 30])
    with open(path, "rb") as handle:
        first = service.ingest_pdf(handle, original_filename="a.pdf")
    assert service.store.point_count() == first.chunk_count
    # Same-document deterministic re-upsert overwrites instead of duplicating.
    record = service.get_document(first.document_id)
    assert record is not None
    from app.documents.validation import extract_pages

    chunks = service._chunk_pages(record, extract_pages(service.storage.original_path(record.stored_filename)))
    service._cleanup_partial_vectors(first.document_id)
    assert service.store.point_count() == 0
    service.store.ensure_collection(service.embedder.dimension)
    vectors = service.embedder.encode([c.text for c in chunks])
    service.store.upsert([c.chunk_id for c in chunks], [list(map(float, r)) for r in vectors],
                         [{**c.to_payload(), "corpus": "dynamic"} for c in chunks], batch_size=4)
    assert service.store.point_count() == first.chunk_count


def test_failed_ingest_cleans_partial_vectors(service, tmp_path) -> None:
    from tests.documents.conftest import make_pdf

    path = tmp_path / "a.pdf"
    make_pdf(path, ["Failure cleanup content. " * 400, "More content page two. " * 400])

    calls = {"n": 0}
    real_encode = service.embedder.encode

    def flaky_encode(texts, *, as_query=False):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise RuntimeError("simulated embedding outage")
        return real_encode(texts, as_query=as_query)

    service.embedder.encode = flaky_encode  # type: ignore[method-assign]
    try:
        with open(path, "rb") as handle:
            result = service.ingest_pdf(handle, original_filename="a.pdf")
    finally:
        service.embedder.encode = real_encode  # type: ignore[method-assign]
    assert result.status == "FAILED"
    assert service.store.point_count() == 0
    record = service.get_document(result.document_id)
    assert record is not None and record.status == "FAILED"
    # Retry with a healthy embedder succeeds.
    with open(path, "rb") as handle:
        retry = service.ingest_pdf(handle, original_filename="a.pdf")
    assert retry.duplicate is True
    assert retry.document_id == result.document_id


def test_document_filter_works(service, tmp_path) -> None:
    from qdrant_client import models

    from tests.documents.conftest import make_pdf

    path = tmp_path / "a.pdf"
    make_pdf(path, ["Filterable pump content. " * 30])
    with open(path, "rb") as handle:
        result = service.ingest_pdf(handle, original_filename="a.pdf")
    assert result.status == "READY"
    filt = models.Filter(must=[models.FieldCondition(
        key="document_id", match=models.MatchValue(value=result.document_id))])
    count = service.store.client.count(service.store.collection, count_filter=filt, exact=True).count
    assert count == result.chunk_count
    other = models.Filter(must=[models.FieldCondition(
        key="document_id", match=models.MatchValue(value="USR-NONEXISTENT"))])
    assert service.store.client.count(service.store.collection, count_filter=other, exact=True).count == 0


def test_real_embedding_dimension() -> None:
    from app.rag.embeddings import build_embedding_model

    model = build_embedding_model("BAAI/bge-small-en-v1.5")
    assert model.dimension == 384
