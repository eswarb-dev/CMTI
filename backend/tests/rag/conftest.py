from __future__ import annotations

import pytest

from app.core.config import Settings, get_settings
from app.rag.ingestion import ChunkBuildResult, build_all_chunks, load_manifest


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="session")
def chunk_build(settings: Settings) -> ChunkBuildResult:
    return build_all_chunks(settings, log_progress=False)


@pytest.fixture(scope="session")
def chunks(chunk_build: ChunkBuildResult):
    return chunk_build.chunks


@pytest.fixture(scope="session")
def vector_store_ready(settings: Settings) -> bool:
    if not settings.vector_store_path.exists():
        return False
    return load_manifest(settings.vector_store_path / "manifest.json") is not None


@pytest.fixture(scope="session")
def retriever(settings: Settings, vector_store_ready: bool):
    if not vector_store_ready:
        pytest.skip("vector store not built; run: python -m app.rag.ingestion")
    from app.rag.retrieval import DocumentRetrieverImpl

    impl = DocumentRetrieverImpl(settings=settings)
    yield impl
    impl.close()


@pytest.fixture(scope="session")
def retrieval_quality(settings: Settings, vector_store_ready: bool, retriever):
    if not vector_store_ready:
        pytest.skip("vector store not built; run: python -m app.rag.ingestion")
    from app.rag.validation import check_retrieval_quality

    # Shares the session retriever: local Qdrant allows only one open client
    # per path, and a second client would silently report zero results.
    return check_retrieval_quality(
        settings, include_vector_checks=False, retriever=retriever
    )


@pytest.fixture
def chunk_factory():
    """Build a fully populated ChunkRecord with sensible defaults."""

    from app.rag.models import ChunkRecord

    def _make(**overrides):
        defaults = dict(
            chunk_id="CHUNK-TEST-0001-0001-0000-AAAAAAAAAA",
            document_id="DOC-TEST",
            filename="test.pdf",
            document_type="OPERATOR_MANUAL",
            source_type="MANUAL",
            manufacturer="ACME",
            machine_family=None,
            model=None,
            revision=None,
            publication_date=None,
            title="Test Manual",
            language="English",
            chapter=None,
            section=None,
            subsection=None,
            heading_path=[],
            page_start=1,
            page_end=1,
            text="body text",
            token_count=10,
            content_hash="hash",
            embedding_model="BAAI/bge-small-en-v1.5",
            ingestion_version="step06.v1",
            document_sha256=None,
            source_relative_path="datasets/raw/test.pdf",
            section_ordinal=1,
            chunk_ordinal=1,
            stable_ordinal=1001,
            section_key="DOC-TEST::prelude",
            heading_method="document_start",
        )
        defaults.update(overrides)
        return ChunkRecord(**defaults)

    return _make
