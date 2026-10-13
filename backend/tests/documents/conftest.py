"""Shared fixtures for dynamic document tests (isolated tmp_path only)."""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from app.core.config import Settings
from app.documents.ingestion import DocumentIngestionService
from app.documents.registry import DocumentRegistry
from app.documents.storage import DocumentStorage
from app.rag.vector_store import VectorStore

DIMENSION = 384


class StubEmbedder:
    """Deterministic offline embedder (no model download)."""

    def __init__(self, dimension: int = DIMENSION) -> None:
        self._dimension = dimension
        self.calls = 0
        self.model_name = "stub"

    @property
    def dimension(self) -> int:
        return self._dimension

    def encode(self, texts, *, as_query: bool = False):
        self.calls += 1
        vectors = []
        for text in texts:
            seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)
            rng = np.random.default_rng(seed)
            vector = rng.standard_normal(self._dimension).astype(np.float32)
            vector /= max(1e-9, float(np.linalg.norm(vector)))
            vectors.append(vector)
        return np.stack(vectors)


@pytest.fixture()
def settings(tmp_path):
    return Settings(
        _env_file=None,
        document_storage_path=str(tmp_path / "storage"),
        document_max_upload_mb=5,
        document_dynamic_collection="test_dynamic_documents",
        document_ingest_batch_size=4,
    )


@pytest.fixture()
def storage(settings):
    return DocumentStorage(settings.document_storage_root)


@pytest.fixture()
def registry(storage):
    registry = DocumentRegistry(storage.registry_dir / "documents.db")
    yield registry
    registry.close()


@pytest.fixture()
def stub_embedder():
    return StubEmbedder()


@pytest.fixture()
def store(storage, settings):
    store = VectorStore(storage.vectors, settings.document_dynamic_collection)
    yield store
    store.close()


@pytest.fixture()
def service(storage, registry, stub_embedder, store, settings):
    return DocumentIngestionService(
        storage=storage, registry=registry, embedder=stub_embedder,
        store=store, settings=settings,
    )


def make_pdf(path, pages: list[str]) -> None:
    """Create a tiny text PDF with fitz (production PDF library)."""

    import fitz

    document = fitz.open()
    for text in pages:
        page = document.new_page()
        rect = fitz.Rect(72, 72, 540, 770)
        page.insert_textbox(rect, text)
    document.save(path)
    document.close()


@pytest.fixture()
def real_embedder():
    """Module-shared real model (loaded once; slow first use)."""

    from app.rag.embeddings import build_embedding_model

    return build_embedding_model("BAAI/bge-small-en-v1.5")
